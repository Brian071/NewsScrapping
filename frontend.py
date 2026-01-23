import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import asyncio
import nest_asyncio

# Force default loop policy for Colab stability
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
try:
    nest_asyncio.apply()
except:
    pass

st.set_page_config(page_title="Auto AI News System", page_icon="🤖", layout="wide")

# --- Session State Initialization ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = pd.DataFrame()
if 'gap_results' not in st.session_state:
    st.session_state.gap_results = pd.DataFrame()
if 'job_id' not in st.session_state:
    st.session_state.job_id = None
if 'job_type' not in st.session_state: # 'batch' or 'gap'
    st.session_state.job_type = None

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

# --- Job Polling Widget ---
def job_polling_widget():
    if st.session_state.job_id:
        st.divider()
        st.info(f"⏳ Background Job Running (ID: {st.session_state.job_id})...")

        try:
            r = requests.get(f"{api_url}/job/{st.session_state.job_id}")
            if r.status_code == 200:
                job_data = r.json()
                status = job_data.get("status")
                processed = job_data.get("processed", 0)
                total = job_data.get("total", 1)
                results = job_data.get("results", [])

                # Progress Bar
                progress = min(1.0, max(0.0, processed / total)) if total > 0 else 0
                st.progress(progress)
                st.write(f"Processed: {processed} / {total}")

                # Preview current results
                if results:
                    st.write(f"Found {len(results)} articles so far...")
                    # Optional: Show snippet
                    # st.dataframe(pd.DataFrame(results).tail(3))

                if status == "completed":
                    st.success("Job Completed!")
                    df_res = pd.DataFrame(results)

                    if st.session_state.job_type == "batch":
                        st.session_state.batch_results = df_res
                    elif st.session_state.job_type == "gap":
                        st.session_state.gap_results = df_res

                    st.session_state.job_id = None
                    st.session_state.job_type = None
                    time.sleep(1)
                    st.rerun()
                elif status == "failed":
                    st.error(f"Job Failed: {job_data.get('msg')}")
                    st.session_state.job_id = None
                    st.session_state.job_type = None
                else:
                    # Still running, refresh
                    time.sleep(2)
                    st.rerun()
            else:
                st.error("Failed to check job status.")
        except Exception as e:
            st.warning(f"Connection issue: {e}")
            time.sleep(5)
            st.rerun()

# ==========================================
# APP A: INPUT & SCRAPING
# ==========================================
if app_mode == "📝 Input & Scraping":
    st.title("📝 Input & Scraping Dashboard")
    
    sub_page = st.sidebar.radio("Menu", ["Input Manual", "Batch Scrape (Auto)", "Gap Filler (Manual Scrape)", "Monitor Data"])

    # Global Job Status
    job_polling_widget()

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
        
        if st.button("Start Batch Scrape", disabled=(st.session_state.job_id is not None)):
            payload = {
                "start_date": str(start), "end_date": str(end),
                "entity": entity, "keywords": kw
            }
            try:
                r = requests.post(f"{api_url}/start_scrape", json=payload)
                if r.status_code == 200:
                    data = r.json()
                    st.session_state.job_id = data["job_id"]
                    st.session_state.job_type = "batch"
                    st.rerun()
                else:
                    st.error(f"Error: {r.text}")
            except Exception as e:
                st.error(f"Connection Error at {api_url}: {e}")

        # Display Results from Session State
        if not st.session_state.batch_results.empty:
            st.divider()
            st.write(f"### 📥 Scraped Results ({len(st.session_state.batch_results)})")

            c_clear, _ = st.columns([1, 5])
            if c_clear.button("🗑️ Clear Results"):
                st.session_state.batch_results = pd.DataFrame()
                st.rerun()

            edited = st.data_editor(st.session_state.batch_results, key="batch_editor")

            if st.button("💾 Save Selected Results"):
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

        if st.button("🔍 Scan & Fill Gaps", disabled=(st.session_state.job_id is not None)):
            payload = {
                "start_date": str(start_gap),
                "end_date": str(end_gap),
                "entity": entity_gap,
                "keywords": kw_gap
            }
            try:
                r = requests.post(f"{api_url}/start_scrape", json=payload)
                if r.status_code == 200:
                    data = r.json()
                    st.session_state.job_id = data["job_id"]
                    st.session_state.job_type = "gap"
                    st.rerun()
                else:
                    st.error(f"Error: {r.text}")
            except Exception as e:
                st.error(f"Connection Error: {e}")

        # Display Results from Session State
        if not st.session_state.gap_results.empty:
            st.divider()
            st.write(f"### 📥 Gap Filler Results ({len(st.session_state.gap_results)})")

            c_clear_gap, _ = st.columns([1, 5])
            if c_clear_gap.button("🗑️ Clear Gap Results"):
                st.session_state.gap_results = pd.DataFrame()
                st.rerun()

            edited_gap = st.data_editor(st.session_state.gap_results, key="gap_editor")
            if st.button("💾 Save Filled Gaps"):
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

        c1, c2, c3, c4 = st.columns(4)
        m_start = c1.date_input("Filter Start Date", value=datetime.now() - timedelta(days=30))
        m_end = c2.date_input("Filter End Date", value=datetime.now())
        m_entity = c3.selectbox("Filter Entity", ["All", "AirAsia", "Garuda Indonesia"])

        if c4.button("Refresh"):
            st.rerun()
        
        df = get_data(api_url)

        if df.empty:
            st.warning("Data kosong atau gagal memuat.")
        else:
            # Apply Filters
            if "Tanggal" in df.columns:
                # Normalize dates
                df["Tanggal"] = pd.to_datetime(df["Tanggal"], errors='coerce')

                mask = (df["Tanggal"] >= pd.to_datetime(m_start)) & (df["Tanggal"] <= pd.to_datetime(m_end))
                if m_entity != "All":
                    mask = mask & (df["Entitas"] == m_entity)

                df_filtered = df[mask].sort_values(by="Tanggal", ascending=False)
                st.write(f"Showing {len(df_filtered)} records.")
                st.dataframe(df_filtered)
            else:
                st.warning("Column 'Tanggal' not found for filtering.")
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
