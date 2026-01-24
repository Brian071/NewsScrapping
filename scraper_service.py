import asyncio
from datetime import datetime, timedelta
from ddgs import DDGS
from newspaper import Article
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode
import gsheet_handler

async def extract_article_content_async(url):
    if not url: return None, None, None
    try:
        # Colab requires no-sandbox and disable-dev-shm-usage to run Chromium
        browser_cfg = BrowserConfig(
            headless=True,
            verbose=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, cache_mode=CacheMode.BYPASS)
            if not result.html:
                print(f"Error: No HTML returned for {url}")
                return "Error", "No HTML", None

            article = Article(url)
            article.set_html(result.html)
            article.parse()

            pub_date = article.publish_date
            pub_date_str = pub_date.strftime("%Y-%m-%d") if pub_date else None
            text = article.text if article.text and len(article.text) > 100 else result.markdown

            return article.title, text, pub_date_str
    except Exception as e:
        print(f"CRITICAL SCRAPER ERROR for {url}: {e}")
        return "Error", str(e), None

def search_duckduckgo(query, max_results=5):
    results = []
    try:
        with DDGS() as ddgs:
            ddgs_gen = ddgs.news(query, region="id-id", safesearch="off", max_results=max_results)
            for r in ddgs_gen:
                results.append(r)
    except Exception as e:
        print(f"DDGS Search Error: {e}")
    return results

async def scrape_batch(start_date, end_date, entity, keywords=""):
    print(f"Starting scrape batch: {start_date} to {end_date} for {entity}")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
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
                if not df_local[(df_local["Tanggal"] == date_str) & (df_local["Entitas"] == entity)].empty:
                    print(f"Skipping {date_str}: Already exists.")
                    return None

            query = f"{entity} {keywords} {date_str}"
            results = await asyncio.to_thread(search_duckduckgo, query)
            print(f"DDGS found {len(results)} results for {date_str}")

            for res in results:
                url = res.get('url')

                # Check DB dup
                if not df_local.empty and "URL" in df_local.columns:
                     if url in df_local["URL"].values:
                         continue

                t, c, pub_date = await extract_article_content_async(url)
                if t and c and len(c) > 200:
                    print(f"Successfully scraped: {t}")
                    return {
                        "Pilih": True,
                        "Tanggal": pub_date if pub_date else date_str,
                        "Entitas": entity,
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
    print(f"Batch complete. Found {len(found)} articles.")
    return found
