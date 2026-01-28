import asyncio
import nest_asyncio
import gc
import re
from datetime import datetime, timedelta
from dateutil import parser as date_parser
# Handle DDGS import warning
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from newspaper import Article
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode
import gsheet_handler
import json
import os
import time
import random

# Enable nest_asyncio
try:
    nest_asyncio.apply()
except Exception:
    pass

TEMP_RESULTS_FILE = "temp_scrape_results.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
]

# --- Core Scraper Functions ---

def find_date_in_text(text):
    """Fallback to find date in text if metadata fails."""
    if not text: return None
    # YYYY-MM-DD
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text[:1000])
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    # DD-MM-YYYY or DD/MM/YYYY
    match = re.search(r'(\d{2})[-/](\d{2})[-/](\d{4})', text[:1000])
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
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
                if article.meta_data:
                    meta_date = article.meta_data.get('date') or article.meta_data.get('pubdate') or article.meta_data.get('publish_date')
                    if meta_date:
                        try:
                            dt = date_parser.parse(str(meta_date))
                            pub_date_str = dt.strftime("%Y-%m-%d")
                        except:
                            pass

                if not pub_date_str:
                    pub_date_str = find_date_in_text(result.html)

            text = article.text if article.text and len(article.text) > 100 else result.markdown
            title = article.title

            del article
            gc.collect()

            return title, text, pub_date_str
    except Exception as e:
        print(f"Scrape Error {url}: {e}")
        return "Error", str(e), None

def search_duckduckgo(query, max_results=5, region="wt-wt"):
    results = []
    max_retries = 3

    # Try 'news' first with API backend, then fallback to 'text' (general search) with default backend (api/auto)
    # Note: backend='html' is deprecated/removed in newer ddgs versions
    methods = [("news", None), ("text", "api")]

    for method, backend in methods:
        # If we already have results from a previous method, stop.
        if results: break

        for attempt in range(max_retries):
            try:
                # Respect rate limits - Jitter
                time.sleep(random.uniform(3, 8))

                ua = random.choice(USER_AGENTS)
                print(f"DEBUG: Searching '{query}' (Method: {method}, Backend: {backend}, Attempt: {attempt+1})")

                # Try to pass headers if supported by installed version
                try:
                    ddgs_instance = DDGS(headers={"User-Agent": ua}, timeout=20)
                except TypeError:
                    ddgs_instance = DDGS(timeout=20)

                with ddgs_instance as ddgs:
                    if method == "news":
                        ddgs_gen = ddgs.news(query, region=region, safesearch="off", max_results=max_results)
                    else:
                        # Fallback to general text search which allows backend='html' (often less strict)
                        # We need to normalize output to match news format (url, title, date)
                        ddgs_gen = []
                        # Note: text() returns 'href', 'title', 'body'
                        raw_res = ddgs.text(query, region=region, safesearch="off", max_results=max_results, backend=backend)
                        for r in raw_res:
                            # Remap to news-like structure
                            ddgs_gen.append({
                                "url": r.get("href"),
                                "title": r.get("title"),
                                "body": r.get("body"),
                                "date": "", # No date in text search usually
                                "source": ""
                            })

                    for r in ddgs_gen:
                        results.append(r)

                if results:
                    break # Success for this method

            except Exception as e:
                print(f"DDGS Error ({method}, Attempt {attempt+1}): {e}")
                time.sleep(random.uniform(5, 10))

    return results

# --- Main Logic with Callbacks ---

async def run_batch_scrape(start_date, end_date, entity, keywords, progress_callback, region="wt-wt"):
    """
    Directly runs the batch scrape and updates UI via callback.
    callback(processed_count, total_count, status_message)
    Returns: List of scraped results (dicts)
    """
    results_list = []
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        delta = (end_dt - start_dt).days + 1

        progress_callback(0, delta, f"Initializing scrape for {entity}...")

        # Load existing data for deduplication
        progress_callback(0, delta, "Loading dataset for deduplication...")
        df_local = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")

        # Load blocked content
        progress_callback(0, delta, "Loading blocked content...")
        df_blocked = gsheet_handler.get_blocked_content()

        existing_urls = set()
        existing_signatures = set()
        existing_titles = set()

        blocked_urls = set()
        blocked_titles = set()

        if not df_local.empty:
            count_loaded = len(df_local)
            progress_callback(0, delta, f"Loaded {count_loaded} records for deduplication.")

            if "URL" in df_local.columns:
                 existing_urls = set(df_local["URL"].dropna().astype(str).str.strip().values)

            for _, row in df_local.iterrows():
                t_raw = str(row.get('Judul', ''))
                t_sig = t_raw.strip().lower()

                if t_sig:
                    existing_titles.add(t_sig)

                d_sig_raw = str(row.get('Tanggal', '')).strip()
                d_sig = d_sig_raw
                try:
                    d_parsed = date_parser.parse(d_sig_raw, dayfirst=True)
                    d_sig = d_parsed.strftime("%Y-%m-%d")
                except:
                    pass

                if t_sig and d_sig:
                    existing_signatures.add((d_sig, t_sig))
        else:
            progress_callback(0, delta, "⚠️ Warning: Dataset empty or failed to load. Duplicates will NOT be filtered.")

        if not df_blocked.empty:
            if "URL" in df_blocked.columns:
                blocked_urls = set(df_blocked["URL"].dropna().astype(str).str.strip().values)
            if "Title" in df_blocked.columns:
                blocked_titles = set(df_blocked["Title"].dropna().astype(str).str.strip().str.lower().values)
            progress_callback(0, delta, f"Loaded {len(df_blocked)} blocked items.")

        job_seen_urls = set()

        # Sequential execution is safer for direct UI updates than complex asyncio gathering
        # but we can still use semaphore if we want concurrency.
        # Let's keep it simple: Loop through dates.

        processed = 0
        for i in range(delta):
            date_obj = start_dt + timedelta(days=i)
            date_str = date_obj.strftime("%Y-%m-%d")

            progress_callback(processed, delta, f"Searching {date_str}...")

            query = f"{entity} {keywords} {date_str}"

            # Pass region if available in params (TODO: Add to run_batch_scrape signature later)
            # For now, default to wt-wt or use global config logic if implemented.
            search_res = await asyncio.to_thread(search_duckduckgo, query, region=region)

            for res in search_res:
                url = res.get('url')
                if not url: continue

                # 1. URL Check (Deduplication + Blocked)
                url_clean = url.strip()
                if url_clean in existing_urls: continue
                if url_clean in blocked_urls: continue
                if url in job_seen_urls: continue

                # 2. Pre-Scrape Title Check (if available from search result)
                search_title = res.get('title', '').strip().lower()
                if search_title:
                    if search_title in existing_titles: continue
                    if search_title in blocked_titles: continue

                job_seen_urls.add(url)

                progress_callback(processed, delta, f"Scraping {url[:30]}...")
                t, c, pub_date = await extract_article_content_async(url)

                if t and c and len(c) > 200:
                    final_date = pub_date if pub_date else ""
                    t_norm = str(t).strip().lower()

                    # 3. Post-Scrape Block/Dedup Check
                    if t_norm in blocked_titles:
                         continue

                    d_norm = str(final_date).strip()
                    if (d_norm, t_norm) in existing_signatures:
                         continue

                    # Double check title against existing titles generally (optional but safer)
                    if t_norm in existing_titles:
                        continue

                    item = {
                        "Tanggal": final_date,
                        "Entitas": entity,
                        "Judul": t,
                        "Isi": c,
                        "URL": url,
                        "Judul_Inggris": "",
                        "Isi_Inggris": ""
                    }
                    results_list.append(item)

                    # 1. Save to Temp File (Persist Local / Session Recovery)
                    # We do NOT save to GSheet automatically anymore (User Request: "Manual Check")
                    try:
                        # Append to JSONL file
                        with open(TEMP_RESULTS_FILE, "a") as f:
                            f.write(json.dumps(item) + "\n")
                    except Exception as e:
                        print(f"Failed to save temp result: {e}")

            processed += 1
            progress_callback(processed, delta, f"Completed {date_str}")

        progress_callback(processed, delta, "Finished!")
        return results_list

    except Exception as e:
        progress_callback(0, 0, f"Error: {str(e)}")
        return []

async def run_search_links(date, entity, keywords):
    query = f"{entity} {keywords} {date}"
    results = await asyncio.to_thread(search_duckduckgo, query, max_results=10, region="wt-wt")

    # Load blocked content & existing data for filtering
    try:
        df_blocked = gsheet_handler.get_blocked_content()
        blocked_urls = set()
        blocked_titles = set()
        if not df_blocked.empty:
            if "URL" in df_blocked.columns:
                blocked_urls = set(df_blocked["URL"].dropna().astype(str).str.strip().values)
            if "Title" in df_blocked.columns:
                blocked_titles = set(df_blocked["Title"].dropna().astype(str).str.strip().str.lower().values)

        df_local = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        existing_urls = set()
        if not df_local.empty and "URL" in df_local.columns:
            existing_urls = set(df_local["URL"].dropna().astype(str).str.strip().values)

    except Exception as e:
        print(f"Error loading block/existing lists in search_links: {e}")
        blocked_urls = set()
        blocked_titles = set()
        existing_urls = set()

    filtered = []
    try:
        req_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        for r in results:
            # Check Blocked / Existing
            url = r.get("url", "").strip()
            title = r.get("title", "").strip().lower()

            if url in blocked_urls or url in existing_urls: continue
            if title in blocked_titles: continue

            d_raw = r.get("date", "")
            include = True
            if d_raw:
                try:
                    d_parsed = date_parser.parse(str(d_raw), dayfirst=True).date()
                    if d_parsed != req_date_obj:
                         include = False
                except:
                     if date not in str(d_raw):
                         pass
            if include:
                filtered.append(r)
    except:
        filtered = results # Fallback

    return filtered
