import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import time
import asyncio
import nest_asyncio

# Local Modules
import gsheet_handler
import scraper_service
import translator_utils

# Enable nested asyncio for Streamlit
try:
    nest_asyncio.apply()
except Exception as e:
    # Log warning if patching fails, but continue to avoid crashing on import
    print(f"WARNING: Failed to patch asyncio loop with nest_asyncio: {e}")

st.set_page_config(page_title="Auto AI News System", page_icon="🤖", layout="wide")

# --- Helper Wrapper ---
def run_async(coroutine):
    """Helper to run async code in Streamlit"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Try patching the specific loop if global patch failed or didn't catch this one
    try:
        nest_asyncio.apply(loop)
    except Exception:
        pass

    return loop.run_until_complete(coroutine)

# --- Config ---
# No more API URL config needed

st.sidebar.title("🤖 Auto AI System")
app_mode = st.sidebar.selectbox("Pilih Aplikasi", ["📝 Input & Scraping", "🔄 Translator"])

# ==========================================
# APP A: INPUT & SCRAPING
# ==========================================
if app_mode == "📝 Input & Scraping":
    st.title("📝 Input & Scraping Dashboard")
    
    sub_page = st.sidebar.radio("Menu", ["Input Manual", "Batch Scrape (Auto)", "Gap Filler (Manual Scrape)", "Monitor Data"])

    # --- 1. INPUT MANUAL ---
    if sub_page == "Input Manual":
        st.subheader("Input Berita Manual")
        c1, c2 = st.columns([1, 2])
        with c1:
            date_input = st.date_input("Tanggal", value=datetime.now())
            entity_input = st.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"])
        with c2:
            with st.form("manual_form"):
                t = st.text_input("Judul")
                c = st.text_area("Isi", height=200)
                if st.form_submit_button("Simpan"):
                    row_data = {
                        "Tanggal": str(date_input),
                        "Entitas": entity_input,
                        "Judul": t,
                        "Isi": c,
                        "Judul_Inggris": "",
                        "Isi_Inggris": ""
                    }
                    try:
                        gsheet_handler.append_to_sheet(row_data)
                        st.success("Tersimpan!")
                    except Exception as e:
                        st.error(f"Error saving: {e}")

    # --- 2. BATCH SCRAPE ---
    elif sub_page == "Batch Scrape (Auto)":
        st.subheader("🚀 Batch Scrape (Async)")
        c1, c2, c3 = st.columns(3)
        start = c1.date_input("Start")
        end = c2.date_input("End")
        entity = c3.selectbox("Entity", ["AirAsia", "Garuda Indonesia"], key="batch_ent")
        kw = st.text_input("Keywords")
        
        if st.button("Start Batch Scrape"):
            with st.spinner("Processing in background (Parallel)..."):
                try:
                    # Run the async scraper directly
                    data = run_async(scraper_service.scrape_batch(
                        start_date=str(start),
                        end_date=str(end),
                        entity=entity,
                        keywords=kw
                    ))

                    st.session_state.batch_results = pd.DataFrame(data)
                    st.success(f"Found {len(data)} articles!")

                except Exception as e:
                    st.error(f"Scraping Error: {e}")
                    
        if 'batch_results' in st.session_state and not st.session_state.batch_results.empty:
            edited = st.data_editor(st.session_state.batch_results)
            if st.button("Save Selected"):
                count = 0
                for _, row in edited.iterrows():
                    if row.get("Pilih", True):
                        clean_data = {
                            "Tanggal": row.get("Tanggal"),
                            "Entitas": row.get("Entitas"),
                            "Judul": row.get("Judul"),
                            "Isi": row.get("Isi"),
                            "URL": row.get("URL", ""),
                            "Judul_Inggris": "",
                            "Isi_Inggris": ""
                        }
                        try:
                            gsheet_handler.append_to_sheet(clean_data)
                            count += 1
                        except Exception as e:
                             st.error(f"Save failed for {row.get('Judul')}: {e}")
                st.success(f"Saved {count} items.")

    # --- 3. GAP FILLER ---
    elif sub_page == "Gap Filler (Manual Scrape)":
        st.subheader("🕵️ Manual Scrape / Gap Filler")
        if st.button("Scan Missing Dates"):
            st.info("Logic pending implementation directly in frontend.")

    # --- 4. MONITOR ---
    elif sub_page == "Monitor Data":
        st.subheader("Data Monitor")
        if st.button("Refresh"):
            st.rerun()
        
        try:
            df = gsheet_handler.read_sheet_to_df()
            if df.empty:
                st.warning("Data kosong atau gagal memuat.")
            else:
                st.dataframe(df)
        except Exception as e:
            st.error(f"Failed to load data: {e}")

# ==========================================
# APP B: TRANSLATOR
# ==========================================
elif app_mode == "🔄 Translator":
    st.title("🔄 Auto Translator")
    
    tab1, tab2 = st.tabs(["Pending", "History"])
    
    # Refresh data
    df = gsheet_handler.read_sheet_to_df()
    
    with tab1:
        if not df.empty:
            if 'Judul_Inggris' in df.columns:
                mask = (df['Judul_Inggris'] == "") | (df['Isi_Inggris'] == "")
                pending = df[mask]
                st.info(f"Pending: {len(pending)}")
                
                edited_pend = st.data_editor(pending, key="pend_edit")
                
                if st.button("Translate Selected"):
                    # Use translator_utils directly
                    with st.spinner("Translating..."):
                        try:
                            processed_df, msg = translator_utils.process_rows(pending, progress=None)
                            st.success(f"Success! {msg}")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Translation Error: {e}")
            else:
                st.warning("Kolom Judul_Inggris tidak ditemukan.")
        else:
            st.warning("Belum ada data.")
    
    with tab2:
        if not df.empty and 'Judul_Inggris' in df.columns:
            mask = (df['Judul_Inggris'] != "")
            hist = df[mask]
            st.dataframe(hist)
