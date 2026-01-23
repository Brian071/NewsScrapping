import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import asyncio
import nest_asyncio

# Force default loop policy for Colab stability (just in case)
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
try:
    nest_asyncio.apply()
except:
    pass

st.set_page_config(page_title="Auto AI News System", page_icon="🤖", layout="wide")

# --- Sidebar Config ---
st.sidebar.title("🤖 Auto AI System")
st.sidebar.header("⚙️ Configuration")
# Default to localhost:8000 as requested
api_url = st.sidebar.text_input("Backend API URL", value="http://localhost:8000")

# --- Helper ---
def get_data(api_url):
    try:
        r = requests.get(f"{api_url}/data")
        if r.status_code == 200:
            data = r.json()
            if not data:
                return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])
            return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Failed to fetch data from {api_url}: {e}")
    return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])

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
                u = st.text_input("URL (Optional)")
                if st.form_submit_button("Simpan"):
                    payload = {
                        "Tanggal": str(date_input),
                        "Entitas": entity_input,
                        "Judul": t,
                        "Isi": c,
                        "URL": u,
                        "Judul_Inggris": "",
                        "Isi_Inggris": ""
                    }
                    try:
                        r = requests.post(f"{api_url}/save", json=payload)
                        if r.status_code == 200:
                            st.success("Tersimpan!")
                        else:
                            st.error(r.text)
                    except Exception as e:
                        st.error(f"Backend Error at {api_url}: {e}")

    # --- 2. BATCH SCRAPE ---
    elif sub_page == "Batch Scrape (Auto)":
        st.subheader("🚀 Batch Scrape (Async)")
        c1, c2, c3 = st.columns(3)
        start = c1.date_input("Start")
        end = c2.date_input("End")
        entity = c3.selectbox("Entity", ["AirAsia", "Garuda Indonesia"], key="batch_ent")
        kw = st.text_input("Keywords")
        
        if st.button("Start Batch Scrape"):
            payload = {
                "start_date": str(start), "end_date": str(end),
                "entity": entity, "keywords": kw
            }
            with st.spinner("Processing in background..."):
                try:
                    r = requests.post(f"{api_url}/scrape", json=payload)
                    if r.status_code == 200:
                        data = r.json()
                        st.session_state.batch_results = pd.DataFrame(data)
                        st.success(f"Found {len(data)} articles!")
                    else:
                        st.error(f"Error: {r.text}")
                except Exception as e:
                    st.error(f"Connection Error at {api_url}: {e}")
                    
        if 'batch_results' in st.session_state and not st.session_state.batch_results.empty:
            edited = st.data_editor(st.session_state.batch_results)
            if st.button("Save Selected"):
                count = 0
                for _, row in edited.iterrows():
                    if row.get("Pilih", True):
                        payload = row.to_dict()
                        try:
                            requests.post(f"{api_url}/save", json=payload)
                            count += 1
                        except Exception as e:
                             st.error(f"Save failed: {e}")
                st.success(f"Saved {count} items.")

    # --- 3. GAP FILLER ---
    elif sub_page == "Gap Filler (Manual Scrape)":
        st.subheader("🕵️ Manual Scrape / Gap Filler")
        st.write("Automatically find missing dates in the database and scrape for them.")

        c1, c2 = st.columns(2)
        entity_gap = c1.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"], key="gap_ent")
        kw_gap = c2.text_input("Keywords", key="gap_kw")

        start_gap = c1.date_input("Range Start", key="gap_start")
        end_gap = c2.date_input("Range End", key="gap_end")

        if st.button("🔍 Scan & Fill Gaps"):
            payload = {
                "start_date": str(start_gap),
                "end_date": str(end_gap),
                "entity": entity_gap,
                "keywords": kw_gap
            }
            with st.spinner("Scanning for missing dates and scraping..."):
                try:
                    # We reuse /scrape but the logic is slightly different:
                    # The backend /scrape already checks for existence (skip if exists).
                    # So calling /scrape acts as a Gap Filler naturally.
                    r = requests.post(f"{api_url}/scrape", json=payload)
                    if r.status_code == 200:
                        data = r.json()
                        if data:
                            st.session_state.gap_results = pd.DataFrame(data)
                            st.success(f"Filled gaps! Found {len(data)} new articles.")
                        else:
                            st.info("No gaps found or no articles found for missing dates.")
                    else:
                        st.error(f"Error: {r.text}")
                except Exception as e:
                     st.error(f"Connection Error: {e}")

        if 'gap_results' in st.session_state and not st.session_state.gap_results.empty:
            st.write("Found Articles:")
            edited_gap = st.data_editor(st.session_state.gap_results)
            if st.button("Save Filled Gaps"):
                count = 0
                for _, row in edited_gap.iterrows():
                    if row.get("Pilih", True):
                        payload = row.to_dict()
                        try:
                            requests.post(f"{api_url}/save", json=payload)
                            count += 1
                        except: pass
                st.success(f"Saved {count} items.")

    # --- 4. MONITOR ---
    elif sub_page == "Monitor Data":
        st.subheader("Data Monitor")
        if st.button("Refresh"):
            st.rerun()
        
        df = get_data(api_url)

        if df.empty:
            st.warning("Data kosong atau gagal memuat.")
        else:
            st.dataframe(df)

# ==========================================
# APP B: TRANSLATOR
# ==========================================
elif app_mode == "🔄 Translator":
    st.title("🔄 Auto Translator")
    
    tab1, tab2 = st.tabs(["Pending", "History"])
    
    # Refresh data
    df = get_data(api_url)
    
    with tab1:
        if not df.empty:
            if 'Judul_Inggris' in df.columns:
                mask = (df['Judul_Inggris'] == "") | (df['Isi_Inggris'] == "")
                pending = df[mask].copy()
                if "Pilih" not in pending.columns:
                    pending.insert(0, "Pilih", True)
                
                st.info(f"Pending: {len(pending)}")
                edited_pend = st.data_editor(pending, key="pend_edit")
                
                if st.button("Translate Selected"):
                    to_translate = edited_pend[edited_pend["Pilih"] == True]
                    if to_translate.empty:
                        st.warning("No rows selected.")
                    else:
                        payload = {"rows": to_translate.to_dict(orient="records")}
                        with st.spinner("Translating..."):
                            try:
                                r = requests.post(f"{api_url}/translate", json=payload)
                                if r.status_code == 200:
                                    st.success("Translated & Updated!")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"API Error: {r.text}")
                            except Exception as e:
                                st.error(f"API Error at {api_url}: {e}")
            else:
                st.warning("Kolom Judul_Inggris tidak ditemukan.")
        else:
            st.warning("Belum ada data.")
    
    with tab2:
        if not df.empty and 'Judul_Inggris' in df.columns:
            mask = (df['Judul_Inggris'] != "")
            hist = df[mask]
            st.dataframe(hist)
