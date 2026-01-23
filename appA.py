import streamlit as st
import pandas as pd
import gsheet_handler
from datetime import datetime, timedelta
from ddgs import DDGS
from newspaper import Article
from gnews import GNews
import requests
import re
import asyncio
import nest_asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode
import os
import calendar

# Apply nest_asyncio to allow nested event loops (crucial for Streamlit + Playwright)
# nest_asyncio.apply() # Might cause issues in some envs, check later if needed.

# --- Page Config ---
st.set_page_config(
    page_title="Input Berita Harian",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS ---
st.markdown("""
<style>
    .stTextArea textarea {
        min-height: 200px;
    }
</style>
""", unsafe_allow_html=True)

# --- Session State Init ---
if 'batch_draft' not in st.session_state:
    st.session_state.batch_draft = pd.DataFrame()
if 'search_results' not in st.session_state:
    st.session_state.search_results = []

# --- Helper Functions ---

def load_data():
    return gsheet_handler.read_sheet_to_df(worksheet_name_or_index=0)

def load_logs():
    return gsheet_handler.get_empty_logs()

# --- Scraping Functions (Async Wrappers) ---

async def extract_article_content_async(url):
    if not url: return None, None, None
    try:
        browser_cfg = BrowserConfig(headless=True, verbose=False)
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, cache_mode=CacheMode.BYPASS)
            rendered_html = result.html
            
            if not rendered_html:
                return "Error", "No HTML returned", None
            
            article = Article(url)
            article.set_html(rendered_html)
            article.parse()
            
            pub_date = article.publish_date
            pub_date_str = pub_date.strftime("%Y-%m-%d") if pub_date else None
            
            text = article.text
            if not text or len(text) < 100:
                text = result.markdown
                
            return article.title, text, pub_date_str
    except Exception as e:
        return "Error", str(e), None

def extract_article_content(url):
    return asyncio.run(extract_article_content_async(url))

def search_duckduckgo(query, search_type="news", max_results=10):
    results = []
    try:
        with DDGS() as ddgs:
            if search_type == "general":
                ddgs_gen = ddgs.text(query, region="id-id", safesearch="off", max_results=max_results)
                for r in ddgs_gen:
                    results.append({'title': r.get('title'), 'url': r.get('href'), 'date': '', 'source': r.get('body', '')[:50]})
            else:
                ddgs_gen = ddgs.news(query, region="id-id", safesearch="off", max_results=max_results)
                for r in ddgs_gen:
                    results.append(r)
    except Exception as e:
        st.error(f"DDG Search Error: {e}")
    return results

# --- Sidebar Navigation ---
st.sidebar.title("Navigasi")
page = st.sidebar.radio("Go to", ["📝 Input & Scraping", "🚀 Batch Scrape", "🕵️ Manual Scrape / Gap Filler", "📊 Dashboard", "🛠️ Manage Data"])

# --- PAGE 1: INPUT & SCRAPING ---
if page == "📝 Input & Scraping":
    st.title("📝 Input Berita Harian")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("1. Metadata")
        date_input = st.date_input("Tanggal", value=datetime.now())
        entity_input = st.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"])
        
        # Live Status Check
        if st.button("Cek Status Harian"):
            df = load_data()
            date_str = str(date_input)
            filtered = df[(df["Tanggal"] == date_str) & (df["Entitas"] == entity_input)]
            count = len(filtered)
            st.info(f"Jumlah Berita Tersimpan: {count}")
            if count > 0:
                with st.expander("Lihat Judul"):
                    st.write(filtered["Judul"].tolist())

    with col2:
        st.subheader("2. Pencarian Berita (Opsional)")
        search_query = st.text_input("Kata Kunci Tambahan", placeholder="Contoh: delay, promo")
        search_source = st.selectbox("Sumber", ["DuckDuckGo News", "DuckDuckGo Web"])
        
        if st.button("🔍 Cari Berita"):
            mode = "news" if "News" in search_source else "general"
            query = f"{entity_input} {search_query} {date_input}"
            results = search_duckduckgo(query, search_type=mode)
            st.session_state.search_results = results
            
        if st.session_state.search_results:
            result_options = {f"{r.get('title')} ({r.get('source')})": r.get('url') for r in st.session_state.search_results}
            selected_res_label = st.selectbox("Pilih Hasil Pencarian", options=list(result_options.keys()))
            
            if st.button("⬇️ Ambil Konten"):
                url = result_options[selected_res_label]
                with st.spinner("Extracting content..."):
                    title, content, pub_date = extract_article_content(url)
                    st.session_state.temp_title = title
                    st.session_state.temp_content = content
                    if pub_date:
                        st.session_state.temp_date = pub_date # We might want to alert user if date mismatch

    st.divider()
    
    st.subheader("3. Form Input Berita")
    
    # Defaults from scraping
    default_title = st.session_state.get('temp_title', "")
    default_content = st.session_state.get('temp_content', "")
    
    with st.form("input_form"):
        title_val = st.text_input("Judul Berita", value=default_title)
        content_val = st.text_area("Isi Berita", value=default_content, height=300)
        
        submitted = st.form_submit_button("💾 SIMPAN KE GOOGLE SHEET")
        
        if submitted:
            if not title_val or not content_val:
                st.error("Judul dan Isi tidak boleh kosong.")
            else:
                try:
                    # Duplicate check
                    df = load_data()
                    date_str = str(date_input)
                    dup = df[
                        (df["Tanggal"] == date_str) & 
                        (df["Entitas"] == entity_input) & 
                        (df["Judul"].str.strip().str.lower() == title_val.strip().lower())
                    ]
                    
                    if not dup.empty:
                        st.error(f"Gagal: Berita ini sudah ada (Tanggal: {date_str}, Entitas: {entity_input}).")
                    else:
                        row_data = {
                            "Tanggal": date_str,
                            "Entitas": entity_input,
                            "Judul": title_val,
                            "Isi": content_val,
                            "Judul_Inggris": "",
                            "Isi_Inggris": ""
                        }
                        gsheet_handler.append_to_sheet(row_data)
                        st.success("✅ Tersimpan ke Google Sheet!")
                        # Clear state
                        st.session_state.temp_title = ""
                        st.session_state.temp_content = ""
                        st.rerun()
                except Exception as e:
                    st.error(f"Error saving: {e}")

# --- PAGE 2: BATCH SCRAPE ---
elif page == "🚀 Batch Scrape":
    st.title("🚀 Batch Scrape")
    st.info("Fitur ini mencari berita secara otomatis untuk rentang tanggal yang dipilih yang **belum ada datanya**.")
    
    col1, col2, col3 = st.columns(3)
    start_date = col1.date_input("Tanggal Awal", value=datetime.now() - timedelta(days=7))
    end_date = col2.date_input("Tanggal Akhir", value=datetime.now())
    entity_batch = col3.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"], key="batch_entity")
    keywords_batch = st.text_input("Kata Kunci Tambahan (Opsional)", placeholder="Contoh: rute baru, saham")
    
    if st.button("🔍 Generate Draft"):
        with st.spinner("Sedang mencari berita... (Mungkin butuh waktu lama)"):
            # Reuse logic from appA.py (async wrapper needed)
            async def run_batch():
                # We need to port generate_batch_draft logic here or import it
                # For simplicity, I'll inline the core logic tailored for Streamlit
                
                # 1. Load Data
                df_local = load_data()
                
                delta = (end_date - start_date).days + 1
                draft_rows = []
                
                seen_urls = set()
                seen_titles = set()
                
                progress_bar = st.progress(0)
                
                for i in range(delta):
                    date_obj = start_date + timedelta(days=i)
                    date_str = date_obj.strftime("%Y-%m-%d")
                    progress_bar.progress((i + 1) / delta)
                    
                    # Skip if exists
                    if not df_local[(df_local["Tanggal"] == date_str) & (df_local["Entitas"] == entity_batch)].empty:
                        continue
                        
                    query = f"{entity_batch} {keywords_batch} {date_str}"
                    results = search_duckduckgo(query, search_type="news", max_results=5)
                    
                    found = False
                    for res in results:
                        url = res.get('url')
                        if url in seen_urls: continue
                        
                        # Basic domain filter
                        if "contact-us" in url or "help" in url: continue
                        
                        # Scrape
                        t, c, pub_date = await extract_article_content_async(url)
                        
                        if not c or len(c) < 200: continue
                        if t in seen_titles: continue
                        
                        # Check duplicate in DB
                        if not df_local[df_local["Judul"].str.strip().str.lower() == t.strip().lower()].empty:
                            continue
                            
                        draft_rows.append({
                            "Pilih": True,
                            "Tanggal": pub_date if pub_date else date_str,
                            "Entitas": entity_batch,
                            "Judul": t,
                            "Isi": c,
                            "URL": url
                        })
                        seen_urls.add(url)
                        seen_titles.add(t)
                        found = True
                        break # One per day per entity preferred? Or remove break to get multiple. Logic said "fill empty days", so break is good.
                
                return pd.DataFrame(draft_rows)

            result_df = asyncio.run(run_batch())
            st.session_state.batch_draft = result_df
            
    # DISPLAY EDITOR
    if not st.session_state.batch_draft.empty:
        st.subheader("Review Draft")
        edited_df = st.data_editor(
            st.session_state.batch_draft,
            column_config={
                "Pilih": st.column_config.CheckboxColumn("Simpan?", default=True),
                "Isi": st.column_config.TextColumn("Isi Berita", width="large"),
                "URL": st.column_config.LinkColumn("URL"),
            },
            disabled=["URL"],
            num_rows="dynamic"
        )
        
        if st.button("💾 Simpan Baris Terpilih"):
            to_save = edited_df[edited_df["Pilih"] == True]
            if to_save.empty:
                st.warning("Tidak ada baris yang dipilih.")
            else:
                count = 0
                for _, row in to_save.iterrows():
                    row_data = {
                        "Tanggal": str(row["Tanggal"]),
                        "Entitas": str(row["Entitas"]),
                        "Judul": str(row["Judul"]),
                        "Isi": str(row["Isi"]),
                        "Judul_Inggris": "",
                        "Isi_Inggris": ""
                    }
                    try:
                        gsheet_handler.append_to_sheet(row_data)
                        count += 1
                    except Exception as e:
                        st.error(f"Error saving {row['Judul']}: {e}")
                
                st.success(f"Berhasil menyimpan {count} berita!")
                st.session_state.batch_draft = pd.DataFrame() # Clear
                st.rerun()
    else:
        st.write("Belum ada draft. Klik Generate Draft.")

# --- PAGE 3: MANUAL SCRAPE / GAP FILLER (NEW) ---
elif page == "🕵️ Manual Scrape / Gap Filler":
    st.title("🕵️ Manual Scrape / Gap Filler")
    st.info("Cari tanggal yang belum memiliki data (kosong), lalu isi secara manual atau tandai sebagai 'Tidak Ada Berita'.")
    
    col1, col2 = st.columns(2)
    start_d = col1.date_input("Dari Tanggal", value=datetime.now() - timedelta(days=30))
    end_d = col2.date_input("Sampai Tanggal", value=datetime.now())
    target_entity = st.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"], key="gap_entity")
    
    if st.button("🔍 Scan Gap Data"):
        with st.spinner("Scanning..."):
            # Fetch data
            df_main = load_data()
            df_log = load_logs()
            
            # Normalize dates
            date_range = pd.date_range(start=start_d, end=end_d)
            all_dates = [d.strftime("%Y-%m-%d") for d in date_range]
            
            # Filter Main Data
            exist_main = set()
            if not df_main.empty:
                df_main_filtered = df_main[df_main["Entitas"] == target_entity]
                exist_main = set(df_main_filtered["Tanggal"].astype(str).tolist())
                
            # Filter Logs
            exist_log = set()
            if not df_log.empty:
                df_log_filtered = df_log[df_log["Entitas"] == target_entity]
                exist_log = set(df_log_filtered["Tanggal"].astype(str).tolist())
                
            missing_data = []
            for d_str in all_dates:
                if d_str not in exist_main and d_str not in exist_log:
                    dt = datetime.strptime(d_str, "%Y-%m-%d")
                    day_name = calendar.day_name[dt.weekday()]
                    is_weekend = "Yes" if dt.weekday() >= 5 else "No"
                    missing_data.append({
                        "Tanggal": d_str,
                        "Hari": day_name,
                        "Weekend": is_weekend
                    })
            
            st.session_state.missing_dates = pd.DataFrame(missing_data)
            
    if 'missing_dates' in st.session_state and not st.session_state.missing_dates.empty:
        st.write(f"Ditemukan **{len(st.session_state.missing_dates)}** tanggal kosong.")
        
        # Selection
        selected_date_row = st.selectbox(
            "Pilih Tanggal untuk Diproses:", 
            st.session_state.missing_dates["Tanggal"].tolist(),
            format_func=lambda x: f"{x} ({st.session_state.missing_dates[st.session_state.missing_dates['Tanggal'] == x]['Hari'].values[0]})"
        )
        
        if selected_date_row:
            st.divider()
            st.subheader(f"Proses Tanggal: {selected_date_row} ({target_entity})")
            
            # Search Links
            query = f"{target_entity} berita {selected_date_row}"
            google_link = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            ddg_link = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            
            st.markdown(f"""
            **Langkah 1: Cari Manual**
            *   [Buka Pencarian Google]({google_link})
            *   [Buka Pencarian DuckDuckGo]({ddg_link})
            """)
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.markdown("### Opsi A: Ditemukan Berita")
                with st.form("manual_found"):
                    m_title = st.text_input("Judul Berita")
                    m_content = st.text_area("Isi Berita")
                    found_submit = st.form_submit_button("💾 Simpan ke Dataset Utama")
                    
                    if found_submit:
                        if m_title and m_content:
                            row_data = {
                                "Tanggal": selected_date_row,
                                "Entitas": target_entity,
                                "Judul": m_title,
                                "Isi": m_content,
                                "Judul_Inggris": "",
                                "Isi_Inggris": ""
                            }
                            try:
                                gsheet_handler.append_to_sheet(row_data)
                                st.success("Tersimpan!")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                        else:
                            st.error("Isi judul dan konten.")
                            
            with col_b:
                st.markdown("### Opsi B: Tidak Ada Berita")
                with st.form("manual_pass"):
                    reason = st.text_input("Alasan (Opsional)", value="Sudah dicek manual, nihil.")
                    pass_submit = st.form_submit_button("🚫 Tandai Kosong (Pass)")
                    
                    if pass_submit:
                        try:
                            gsheet_handler.log_empty_date(selected_date_row, target_entity, reason)
                            st.success("Ditandai kosong!")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                            
    elif 'missing_dates' in st.session_state:
        st.success("Semua tanggal sudah terisi atau ditandai!")

# --- PAGE 5: DASHBOARD ---
elif page == "📊 Dashboard":
    st.title("📊 Dashboard Monitoring")
    
    col1, col2 = st.columns(2)
    start_d = col1.date_input("Dari", value=datetime.now() - timedelta(days=30))
    end_d = col2.date_input("Sampai", value=datetime.now())
    
    if st.button("Refresh Data"):
        st.rerun()
        
    df = load_data()
    
    # Filter by date range
    # Ensure Tanggal is datetime
    try:
        df['Tanggal_DT'] = pd.to_datetime(df['Tanggal'], errors='coerce')
        mask = (df['Tanggal_DT'].dt.date >= start_d) & (df['Tanggal_DT'].dt.date <= end_d)
        filtered_df = df[mask]
    except:
        filtered_df = df
        
    # Pivot for summary
    if not filtered_df.empty:
        summary = filtered_df.groupby(['Tanggal', 'Entitas']).size().unstack(fill_value=0)
        st.bar_chart(summary)
        st.dataframe(summary)
    else:
        st.warning("Data kosong untuk rentang tanggal ini.")

# --- PAGE 6: MANAGE DATA ---
elif page == "🛠️ Manage Data":
    st.title("🛠️ Kelola Data (Edit / Hapus)")
    
    col1, col2 = st.columns(2)
    m_date = col1.date_input("Tanggal Data", value=datetime.now())
    m_entity = col2.selectbox("Entitas Data", ["AirAsia", "Garuda Indonesia"])
    
    if st.button("📂 Load Data"):
        df = load_data()
        date_str = str(m_date)
        filtered = df[(df["Tanggal"] == date_str) & (df["Entitas"] == m_entity)]
        st.session_state.manage_data = filtered
    
    if 'manage_data' in st.session_state and not st.session_state.manage_data.empty:
        titles = st.session_state.manage_data["Judul"].tolist()
        selected_title = st.selectbox("Pilih Berita untuk Diedit", titles)
        
        if selected_title:
            row = st.session_state.manage_data[st.session_state.manage_data["Judul"] == selected_title].iloc[0]
            
            with st.form("edit_form"):
                new_title = st.text_input("Judul", value=row["Judul"])
                new_content = st.text_area("Isi", value=row["Isi"], height=300)
                
                c1, c2 = st.columns(2)
                update_btn = c1.form_submit_button("💾 Update (Simpan Perubahan)")
                delete_btn = c2.form_submit_button("🗑️ Hapus Data", type="primary")
                
                if update_btn:
                    try:
                        gsheet_handler.update_row_in_sheet(
                            str(m_date), m_entity, selected_title,
                            {"Judul": new_title, "Isi": new_content}
                        )
                        st.success("Data berhasil diupdate!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal update: {e}")
                        
                if delete_btn:
                    try:
                        gsheet_handler.delete_row_from_sheet(str(m_date), m_entity, selected_title)
                        st.success("Data berhasil dihapus!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal hapus: {e}")
    elif 'manage_data' in st.session_state:
        st.warning("Tidak ada data ditemukan untuk tanggal/entitas ini.")
