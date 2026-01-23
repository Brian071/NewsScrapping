import asyncio
import nest_asyncio

# FORCE Standard Event Loop Policy to avoid UVLoop conflicts with nest_asyncio
try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except Exception as e:
    print(f"WARNING: Could not set event loop policy: {e}")

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import gsheet_handler
import pandas as pd
from datetime import datetime, timedelta
from ddgs import DDGS
from newspaper import Article
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode
import torch
from transformers import pipeline
from llama_index.core.node_parser import SentenceSplitter
import os
import gc

# Enable nest_asyncio for Crawl4AI in API
try:
    nest_asyncio.apply()
except Exception as e:
    print(f"WARNING: nest_asyncio apply failed: {e}")

app = FastAPI()

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

# --- Resources (Lazy Loading) ---
_translator = None
_splitter = None

def get_translator():
    global _translator
    if _translator is None:
        print("Loading NLLB-200 model (Lazy Load)...")
        device = 0 if torch.cuda.is_available() else -1
        # Use lighter model if full version crashes: facebook/nllb-200-distilled-600M
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
        # Minimal config safe for Colab
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

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/data")
def get_data():
    print("DEBUG: Fetching data from Google Sheet...")
    try:
        df = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        print(f"DEBUG: Retrieved {len(df)} rows. Columns: {df.columns.tolist()}")
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
        # Clean up dict
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

@app.post("/scrape")
async def scrape_batch(req: ScrapeRequest):
    start_dt = datetime.strptime(req.start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(req.end_date, "%Y-%m-%d")
    delta = (end_dt - start_dt).days + 1
    
    # Load existing to skip
    df_local = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
    
    tasks = []
    
    # Semaphore to limit concurrency
    sem = asyncio.Semaphore(5)

    async def process_date(date_obj):
        async with sem:
            date_str = date_obj.strftime("%Y-%m-%d")
            
            # Check exist
            if not df_local.empty:
                if not df_local[(df_local["Tanggal"] == date_str) & (df_local["Entitas"] == req.entity)].empty:
                    return None

            query = f"{req.entity} {req.keywords} {date_str}"
            results = await asyncio.to_thread(search_duckduckgo, query)
            
            for res in results:
                url = res.get('url')
                # Check DB dup by URL
                if not df_local.empty and "URL" in df_local.columns:
                     if url in df_local["URL"].values:
                         continue
                
                t, c, pub_date = await extract_article_content_async(url)
                if t and c and len(c) > 200:
                    return {
                        "Pilih": True,
                        "Tanggal": pub_date if pub_date else date_str,
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
        
    results = await asyncio.gather(*tasks)
    # Filter None
    found = [r for r in results if r]
    return found

@app.post("/translate")
async def translate_batch(req: TranslateRequest):
    results = []
    # Trigger model load only here
    get_translator()
    
    for row in req.rows:
        # Check if already translated
        j_ing = row.Judul_Inggris
        i_ing = row.Isi_Inggris
        
        updated_fields = {}
        
        if not j_ing:
            j_ing = smart_translate(row.Judul)
            updated_fields["Judul_Inggris"] = j_ing
            
        if not i_ing:
            i_ing = smart_translate(row.Isi)
            updated_fields["Isi_Inggris"] = i_ing
            
        # Update Sheet immediately
        if updated_fields:
            try:
                gsheet_handler.update_row_in_sheet(row.Tanggal, row.Entitas, row.Judul, updated_fields)
            except Exception as e:
                print(f"Update failed for {row.Judul}: {e}")
        
        # Return updated object
        row.Judul_Inggris = j_ing
        row.Isi_Inggris = i_ing
        results.append(row)
    
    # Try to cleanup memory if heavy
    # gc.collect()
    return results
