import asyncio
import nest_asyncio
import uuid
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import gsheet_handler
import db_handler
import pandas as pd
from datetime import datetime, timedelta
from duckduckgo_search import DDGS
from newspaper import Article
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode
import torch
from transformers import pipeline
from llama_index.core.node_parser import SentenceSplitter
import os
import gc
import re
from dateutil import parser as date_parser

# FORCE Standard Event Loop Policy
try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except Exception as e:
    print(f"WARNING: Could not set event loop policy: {e}")

# Enable nest_asyncio
try:
    nest_asyncio.apply()
except Exception as e:
    print(f"WARNING: nest_asyncio apply failed: {e}")

app = FastAPI()

# Initialize DB (This will check for Drive/Colab path)
db_handler.init_db()

# --- Models ---
class ScrapeRequest(BaseModel):
    start_date: str
    end_date: str
    entity: str
    keywords: str = ""

class ArticleData(BaseModel):
    Tanggal: str
    Entitas: str
    Judul: str
    Isi: str
    Judul_Inggris: str = ""
    Isi_Inggris: str = ""
    Pilih: bool = False
    URL: str = ""

class UpdateRequest(BaseModel):
    date: str
    entity: str
    old_title: str
    new_data: Dict[str, Any]

class DeleteRequest(BaseModel):
    date: str
    entity: str
    title: str

class LogEmptyRequest(BaseModel):
    date: str
    entity: str
    reason: str

class TranslateRequest(BaseModel):
    rows: List[ArticleData]

class UrlScrapeRequest(BaseModel):
    url: str

class SearchLinksRequest(BaseModel):
    date: str
    entity: str
    keywords: str = ""

# --- Resources (Lazy Loading) ---
_translator = None
_splitter = None

def get_translator():
    global _translator
    if _translator is None:
        print("Loading NLLB-200 model (Lazy Load)...")
        device = 0 if torch.cuda.is_available() else -1
        _translator = pipeline("translation", model="facebook/nllb-200-distilled-600M", src_lang="ind_Latn", tgt_lang="eng_Latn", device=device)
    return _translator

def get_splitter():
    global _splitter
    if _splitter is None:
        print("Loading SentenceSplitter (Lazy Load)...")
        _splitter = SentenceSplitter(chunk_size=64, chunk_overlap=0)
    return _splitter

def smart_translate(text):
    translator = get_translator()
    splitter = get_splitter()
    
    if not text or not isinstance(text, str) or text.strip() == "":
        return ""
    chunks = splitter.split_text(text)
    translated_parts = []
    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            res = translator(chunk, max_length=512, truncation=True)
            translated_parts.append(res[0]['translation_text'])
        except Exception:
            translated_parts.append(chunk)
    return " ".join(translated_parts)

# --- Scraping Logic ---
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
            verbose=True
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

# --- Async Worker ---
async def run_scrape_job(job_id: str, req: ScrapeRequest):
    try:
        # SQLite: Update Status
        db_handler.update_job_status(job_id, "running")
        print(f"Starting Job {job_id} for {req.entity}...")

        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(req.end_date, "%Y-%m-%d")

        if start_dt > end_dt:
            raise ValueError(f"Start date {req.start_date} cannot be after End date {req.end_date}")

        delta = (end_dt - start_dt).days + 1

        # SQLite: Update Total
        conn = db_handler.get_conn()
        conn.execute("UPDATE jobs SET total = ?, current_action = ? WHERE job_id = ?",
                     (delta, f"Starting scrape for {req.entity} ({delta} days)", job_id))
        conn.commit()
        conn.close()

        df_local = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        existing_urls = set()
        existing_signatures = set()

        if not df_local.empty:
            if "URL" in df_local.columns:
                 existing_urls = set(df_local["URL"].dropna().astype(str).values)

            for _, row in df_local.iterrows():
                # Normalize title: strip + lower
                t_sig = str(row.get('Judul', '')).strip().lower()
                d_sig_raw = str(row.get('Tanggal', '')).strip()
                d_sig = d_sig_raw
                try:
                    # Normalize date to YYYY-MM-DD
                    d_parsed = date_parser.parse(d_sig_raw)
                    d_sig = d_parsed.strftime("%Y-%m-%d")
                except:
                    pass

                if t_sig and d_sig:
                    existing_signatures.add((d_sig, t_sig))

        job_seen_urls = set()
        tasks = []
        sem = asyncio.Semaphore(5)

        async def process_date(date_obj):
            async with sem:
                date_str = date_obj.strftime("%Y-%m-%d")

                # SQLite: Update Action (Progress)
                db_handler.update_job_progress(job_id, processed=None, action=f"Processing {date_str}...")

                query = f"{req.entity} {req.keywords} {date_str}"
                results = await asyncio.to_thread(search_duckduckgo, query)

                for res in results:
                    url = res.get('url')
                    if not url: continue

                    if url in existing_urls: continue
                    if url in job_seen_urls: continue

                    job_seen_urls.add(url)

                    t, c, pub_date = await extract_article_content_async(url)
                    if t and c and len(c) > 200:
                        # Check existing signatures
                        final_date = pub_date if pub_date else ""
                        t_norm = str(t).strip().lower()
                        d_norm = str(final_date).strip()

                        if (d_norm, t_norm) in existing_signatures:
                            print(f"Skipping Duplicate (Date+Title): {d_norm} - {t}")
                            continue

                        # SQLite: Save Result Immediately
                        db_handler.save_result(job_id, final_date, req.entity, t, c, url)
                        return True
                return None

        for i in range(delta):
            date_obj = start_dt + timedelta(days=i)
            tasks.append(process_date(date_obj))

        processed_count = 0
        for future in asyncio.as_completed(tasks):
            res = await future
            processed_count += 1
            # SQLite: Update Processed Count
            db_handler.update_job_progress(job_id, processed=processed_count)

            # Periodic GC
            if processed_count % 5 == 0:
                gc.collect()

        # --- SYNC TO DRIVE (via Google Sheets) ---
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
                    print(f"Synced {len(sync_data)} articles to Drive.")
                except Exception as e:
                    print(f"Sync failed: {e}")
                    db_handler.update_job_status(job_id, "failed", f"Scrape done but Sync failed: {e}")
                    return

        db_handler.update_job_status(job_id, "completed")
        print(f"Job {job_id} Completed.")

    except Exception as e:
        print(f"Job {job_id} Failed: {e}")
        db_handler.update_job_status(job_id, "failed", str(e))

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/data")
def get_data():
    try:
        df = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"ERROR in /data: {e}")
        return []

@app.get("/logs")
def get_logs():
    df = gsheet_handler.get_empty_logs()
    return df.to_dict(orient="records")

@app.post("/save")
def save_entry(row: ArticleData):
    try:
        data = row.dict()
        clean_data = {k: v for k, v in data.items() if k in ["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"]}
        gsheet_handler.append_to_sheet(clean_data)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update")
def update_entry(req: UpdateRequest):
    try:
        gsheet_handler.update_row_in_sheet(req.date, req.entity, req.old_title, req.new_data)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete")
def delete_entry(req: DeleteRequest):
    try:
        gsheet_handler.delete_row_from_sheet(req.date, req.entity, req.title)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/log_empty")
def log_empty(req: LogEmptyRequest):
    try:
        gsheet_handler.log_empty_date(req.date, req.entity, req.reason)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Job Endpoints ---

@app.post("/start_scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    # Initialize Job in SQLite
    db_handler.create_job(job_id, "queued")

    background_tasks.add_task(run_scrape_job, job_id, req)
    return {"job_id": job_id}

@app.get("/job/{job_id}")
def get_job_status(job_id: str):
    # Retrieve from SQLite
    job = db_handler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Attach results (from local DB) so frontend can display them
    results = db_handler.get_job_results(job_id)
    job["results"] = results

    return job

@app.post("/scrape_url")
async def scrape_url(req: UrlScrapeRequest):
    try:
        t, c, pub_date = await extract_article_content_async(req.url)
        if t == "Error":
             raise HTTPException(status_code=500, detail=c)
        return {"Judul": t, "Isi": c, "Tanggal": pub_date}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search_links")
async def search_links(req: SearchLinksRequest):
    try:
        query = f"{req.entity} {req.keywords} {req.date}"
        results = await asyncio.to_thread(search_duckduckgo, query, max_results=10)

        # Strict Filtering: Only return results that match the requested date
        filtered_results = []
        req_date_obj = datetime.strptime(req.date, "%Y-%m-%d").date()

        for r in results:
            d_raw = r.get("date", "")
            if d_raw:
                try:
                    # Parse the date from DDGS
                    d_parsed = date_parser.parse(str(d_raw)).date()

                    # Strict match: Must be equal
                    if d_parsed == req_date_obj:
                        filtered_results.append(r)
                except:
                    # If date is unparseable, we can't be sure.
                    # User wants STRICT ("harus seacrh berdasarkan tanggal yg di berikan").
                    # So if we have a date string but can't parse it to verify, maybe we should be careful?
                    # But usually DDGS dates are parseable.
                    # If we exclude it, we might miss data.
                    # If we include it, we might include wrong data.
                    # "bukan hasilnya menggunakan tanggal yg berbeda" -> imply if different, reject.
                    # If unparseable, we don't know if it is different.
                    # Use "keep" policy for unparseable?
                    # Let's check if the raw string contains the date substring.
                    if req.date in str(d_raw):
                         filtered_results.append(r)
            else:
                # No date provided by DDGS -> Keep it
                filtered_results.append(r)

        return filtered_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/translate")
async def translate_batch(req: TranslateRequest):
    results = []
    get_translator()
    
    for row in req.rows:
        j_ing = row.Judul_Inggris
        i_ing = row.Isi_Inggris
        updated_fields = {}
        
        if not j_ing:
            j_ing = smart_translate(row.Judul)
            updated_fields["Judul_Inggris"] = j_ing
            
        if not i_ing:
            i_ing = smart_translate(row.Isi)
            updated_fields["Isi_Inggris"] = i_ing
            
        if updated_fields:
            try:
                gsheet_handler.update_row_in_sheet(row.Tanggal, row.Entitas, row.Judul, updated_fields)
            except Exception as e:
                print(f"Update failed: {e}")
        
        row.Judul_Inggris = j_ing
        row.Isi_Inggris = i_ing
        results.append(row)
    
    return results
