import asyncio
import nest_asyncio
import uuid
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import gsheet_handler
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

# --- Global Job Store ---
JOBS = {}

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
            article.parse()
            
            pub_date = article.publish_date
            pub_date_str = pub_date.strftime("%Y-%m-%d") if pub_date else None
            text = article.text if article.text and len(article.text) > 100 else result.markdown
            
            return article.title, text, pub_date_str
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
        JOBS[job_id]["status"] = "running"
        print(f"Starting Job {job_id} for {req.entity}...")

        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(req.end_date, "%Y-%m-%d")

        if start_dt > end_dt:
            raise ValueError(f"Start date {req.start_date} cannot be after End date {req.end_date}")

        delta = (end_dt - start_dt).days + 1
        JOBS[job_id]["total"] = delta
        JOBS[job_id]["current_action"] = f"Starting scrape for {req.entity} ({delta} days)"

        df_local = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        existing_urls = set(df_local["URL"].dropna().values) if not df_local.empty and "URL" in df_local.columns else set()

        # Enhanced Deduplication: Check (Date, Title) signature
        existing_signatures = set()
        if not df_local.empty:
            for _, row in df_local.iterrows():
                # Normalize title: strip + lower
                t_sig = str(row.get('Judul', '')).strip().lower()
                d_sig = str(row.get('Tanggal', '')).strip()
                if t_sig and d_sig:
                    existing_signatures.add((d_sig, t_sig))

        job_seen_urls = set()
        tasks = []
        sem = asyncio.Semaphore(5)

        async def process_date(date_obj):
            async with sem:
                date_str = date_obj.strftime("%Y-%m-%d")
                JOBS[job_id]["current_action"] = f"Processing {date_str}..."

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
                        final_date = pub_date if pub_date else date_str
                        t_norm = str(t).strip().lower()
                        d_norm = str(final_date).strip()

                        if (d_norm, t_norm) in existing_signatures:
                            print(f"Skipping Duplicate (Date+Title): {d_norm} - {t}")
                            continue

                        return {
                            "Pilih": True,
                            "Tanggal": final_date,
                            "Entitas": req.entity,
                            "Judul": t,
                            "Isi": c,
                            "URL": url,
                            "Judul_Inggris": "",
                            "Isi_Inggris": ""
                        }
                return None

        for i in range(delta):
            date_obj = start_dt + timedelta(days=i)
            tasks.append(process_date(date_obj))

        processed_count = 0
        for future in asyncio.as_completed(tasks):
            res = await future
            processed_count += 1
            JOBS[job_id]["processed"] = processed_count
            if res:
                JOBS[job_id]["results"].append(res)

        JOBS[job_id]["status"] = "completed"
        print(f"Job {job_id} Completed. Found {len(JOBS[job_id]['results'])} articles.")

    except Exception as e:
        print(f"Job {job_id} Failed: {e}")
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["msg"] = str(e)

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
    JOBS[job_id] = {
        "status": "queued",
        "results": [],
        "msg": "",
        "total": 0,
        "processed": 0,
        "created_at": time.time(),
        "current_action": "Initializing..."
    }
    background_tasks.add_task(run_scrape_job, job_id, req)
    return {"job_id": job_id}

@app.get("/job/{job_id}")
def get_job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
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
        # DDGS usually returns 'date' in ISO format or similar
        filtered_results = []
        for r in results:
            d = r.get("date", "")
            # If date exists, it MUST match
            if d:
                if str(d).startswith(req.date):
                    filtered_results.append(r)
            else:
                # If date is missing/unsure, keep it (User: "if you not sure... insert data")
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
