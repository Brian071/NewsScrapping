import asyncio
import nest_asyncio
import time
import json
import traceback
import gc
import re
import os
from datetime import datetime, timedelta
from dateutil import parser as date_parser

# Third-party libraries
from duckduckgo_search import DDGS
from newspaper import Article
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode
import db_handler
import gsheet_handler
import pandas as pd

# FORCE Standard Event Loop Policy for Colab/Jupyter compatibility
try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except Exception as e:
    print(f"WARNING: Could not set event loop policy: {e}")

# Enable nest_asyncio
try:
    nest_asyncio.apply()
except Exception as e:
    print(f"WARNING: nest_asyncio apply failed: {e}")

# --- Helper Functions (Ported from api.py) ---

def find_date_in_text(text):
    """Fallback to find date in text if metadata fails."""
    if not text: return None
    # YYYY-MM-DD
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text[:1000]) # Look in first 1000 chars
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    # DD-MM-YYYY or DD/MM/YYYY
    match = re.search(r'(\d{2})[-/](\d{2})[-/](\d{4})', text[:1000])
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" # Convert to YYYY-MM-DD
    return None

async def extract_article_content_async(url):
    if not url: return None, None, None
    try:
        browser_cfg = BrowserConfig(
            headless=True,
            verbose=False
        )

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, cache_mode=CacheMode.BYPASS)
            if not result.html: return "Error", "No HTML", None

            article = Article(url)
            article.set_html(result.html)
            await asyncio.to_thread(article.parse)

            pub_date = article.publish_date
            pub_date_str = None

            if pub_date:
                pub_date_str = pub_date.strftime("%Y-%m-%d")
            else:
                # Fallback: Try metadata
                if article.meta_data:
                    # Common meta tags for date
                    meta_date = article.meta_data.get('date') or article.meta_data.get('pubdate') or article.meta_data.get('publish_date')
                    if meta_date:
                        try:
                            dt = date_parser.parse(str(meta_date))
                            pub_date_str = dt.strftime("%Y-%m-%d")
                        except:
                            pass

                # Fallback: Regex in text/html
                if not pub_date_str:
                    pub_date_str = find_date_in_text(result.html) # HTML is better for meta tags in header that Newspaper missed

            text = article.text if article.text and len(article.text) > 100 else result.markdown
            title = article.title # Store title before deletion

            # Memory Cleanup
            del article
            gc.collect()

            return title, text, pub_date_str
    except Exception as e:
        print(f"Scrape Error {url}: {e}")
        return "Error", str(e), None

def search_duckduckgo(query, max_results=5):
    results = []
    try:
        with DDGS() as ddgs:
            ddgs_gen = ddgs.news(query, region="id-id", safesearch="off", max_results=max_results)
            for r in ddgs_gen:
                results.append(r)
    except Exception as e:
        print(f"DDGS Error: {e}")
    return results

# --- Job Processors ---

async def process_batch_scrape(job_id, params):
    """
    Handles the main scraping logic (formerly run_scrape_job in api.py).
    """
    try:
        start_date = params.get('start_date')
        end_date = params.get('end_date')
        entity = params.get('entity')
        keywords = params.get('keywords', '')

        db_handler.update_job_status(job_id, "running")
        print(f"Starting Job {job_id} for {entity}...")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        if start_dt > end_dt:
            raise ValueError(f"Start date {start_date} cannot be after End date {end_date}")

        delta = (end_dt - start_dt).days + 1

        conn = db_handler.get_conn()
        conn.execute("UPDATE jobs SET total = ?, current_action = ? WHERE job_id = ?",
                     (delta, f"Starting scrape for {entity} ({delta} days)", job_id))
        conn.commit()
        conn.close()

        # Load existing data for deduplication
        df_local = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        existing_urls = set()
        existing_signatures = set()

        if not df_local.empty:
            if "URL" in df_local.columns:
                 existing_urls = set(df_local["URL"].dropna().astype(str).values)

            for _, row in df_local.iterrows():
                t_sig = str(row.get('Judul', '')).strip().lower()
                d_sig_raw = str(row.get('Tanggal', '')).strip()
                d_sig = d_sig_raw
                try:
                    d_parsed = date_parser.parse(d_sig_raw)
                    d_sig = d_parsed.strftime("%Y-%m-%d")
                except:
                    pass

                if t_sig and d_sig:
                    existing_signatures.add((d_sig, t_sig))

        job_seen_urls = set()
        tasks = []
        sem = asyncio.Semaphore(2) # Conservative concurrency

        async def process_date(date_obj):
            async with sem:
                date_str = date_obj.strftime("%Y-%m-%d")
                db_handler.update_job_progress(job_id, processed=None, action=f"Processing {date_str}...")

                query = f"{entity} {keywords} {date_str}"
                results = await asyncio.to_thread(search_duckduckgo, query)

                for res in results:
                    url = res.get('url')
                    if not url: continue
                    if url in existing_urls: continue
                    if url in job_seen_urls: continue

                    job_seen_urls.add(url)

                    t, c, pub_date = await extract_article_content_async(url)
                    if t and c and len(c) > 200:
                        final_date = pub_date if pub_date else ""
                        t_norm = str(t).strip().lower()
                        d_norm = str(final_date).strip()

                        if (d_norm, t_norm) in existing_signatures:
                            print(f"Skipping Duplicate (Date+Title): {d_norm} - {t}")
                            continue

                        # Save Result
                        db_handler.save_result(job_id, final_date, entity, t, c, url)
                        return True
                return None

        for i in range(delta):
            date_obj = start_dt + timedelta(days=i)
            tasks.append(process_date(date_obj))

        processed_count = 0
        for future in asyncio.as_completed(tasks):
            await future
            processed_count += 1
            db_handler.update_job_progress(job_id, processed=processed_count)
            if processed_count % 5 == 0:
                gc.collect()

        # Sync to Drive
        db_handler.update_job_status(job_id, "running", "Syncing to Drive...")
        unsynced = db_handler.get_unsynced_results(job_id)
        if unsynced:
            sync_data = []
            ids_to_mark = []
            for r in unsynced:
                sync_data.append({
                    "Tanggal": r["date"],
                    "Entitas": r["entity"],
                    "Judul": r["title"],
                    "Isi": r["content"],
                    "Judul_Inggris": "",
                    "Isi_Inggris": "",
                    "URL": r["url"]
                })
                ids_to_mark.append(r["id"])

            if sync_data:
                df_batch = pd.DataFrame(sync_data)
                try:
                    gsheet_handler.bulk_append(df_batch)
                    db_handler.mark_results_synced(ids_to_mark)
                except Exception as e:
                    print(f"Sync failed: {e}")
                    db_handler.update_job_status(job_id, "failed", f"Scrape done but Sync failed: {e}")
                    return

        db_handler.update_job_status(job_id, "completed")
        print(f"Job {job_id} Completed.")

    except Exception as e:
        print(f"Job {job_id} Failed: {e}")
        traceback.print_exc()
        db_handler.update_job_status(job_id, "failed", str(e))

async def process_search_links(job_id, params):
    """
    Handles 'Search Links' request for Manual Input.
    Does DDGS search and stores results in a format Frontend can read.
    We will use 'job_results' but with empty content to signify it's just a link.
    """
    try:
        db_handler.update_job_status(job_id, "running")
        entity = params.get('entity')
        keywords = params.get('keywords', '')
        date_str = params.get('date')

        query = f"{entity} {keywords} {date_str}"
        results = await asyncio.to_thread(search_duckduckgo, query, max_results=10)

        # Filter strict date
        req_date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

        for r in results:
            d_raw = r.get("date", "")
            include = True
            if d_raw:
                try:
                    d_parsed = date_parser.parse(str(d_raw)).date()
                    if d_parsed != req_date_obj:
                        include = False
                except:
                    if date_str not in str(d_raw):
                        pass # lenient include if unparseable

            if include:
                # Save as a "Result" but maybe mark it specially?
                # Or just put it in. Frontend needs URL, Title, Date.
                # Content is empty because we haven't scraped it yet.
                db_handler.save_result(
                    job_id,
                    date_str,
                    entity,
                    r.get('title', 'No Title'),
                    "", # No content yet
                    r.get('url')
                )

        db_handler.update_job_status(job_id, "completed")

    except Exception as e:
        print(f"Search Job {job_id} Failed: {e}")
        db_handler.update_job_status(job_id, "failed", str(e))

async def process_scrape_url(job_id, params):
    """
    Handles 'Scrape URL' for a single URL.
    """
    try:
        db_handler.update_job_status(job_id, "running")
        url = params.get('url')

        t, c, pub_date = await extract_article_content_async(url)

        if t == "Error":
            raise Exception(f"Scrape failed: {c}")

        # Save result
        db_handler.save_result(job_id, pub_date, "", t, c, url)

        db_handler.update_job_status(job_id, "completed")

    except Exception as e:
        print(f"URL Scrape Job {job_id} Failed: {e}")
        db_handler.update_job_status(job_id, "failed", str(e))


# --- Main Worker Loop ---

async def worker_loop():
    print("Worker started. Waiting for jobs...")

    # Initialize DB (creates tables if needed)
    db_handler.init_db()

    while True:
        try:
            job_id = db_handler.get_next_queued_job()
            if job_id:
                print(f"Picked up job: {job_id}")
                params = db_handler.get_job_params(job_id)
                job_type = params.get('job_type', 'batch_scrape')

                if job_type == 'batch_scrape':
                    await process_batch_scrape(job_id, params)
                elif job_type == 'search_links':
                    await process_search_links(job_id, params)
                elif job_type == 'scrape_url':
                    await process_scrape_url(job_id, params)
                else:
                    print(f"Unknown job type: {job_type}")
                    db_handler.update_job_status(job_id, "failed", "Unknown job type")
            else:
                await asyncio.sleep(2) # Poll interval
        except Exception as e:
            print(f"Worker Loop Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        print("Worker stopped.")
