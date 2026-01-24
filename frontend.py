import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import calendar
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

# --- Backend Health Check ---
def check_backend_health(url):
    try:
        r = requests.get(f"{url}/health", timeout=2)
        return r.status_code == 200
    except:
        return False

# Perform check immediately
if not check_backend_health(api_url):
    st.error(f"❌ Cannot connect to Backend API at `{api_url}`")
    st.warning("Please ensure the backend server is running.")
    st.info("If running in Colab/Notebook, make sure the cell executing `api.py` (FastAPI) is active and running.")
    if st.button("Retry Connection"):
        st.rerun()
    st.stop()

# --- Helper ---
def serialize_payload(payload):
    """Ensure all values in payload are JSON serializable (convert timestamps to str)."""
    clean = {}
    for k, v in payload.items():
        if isinstance(v, (pd.Timestamp, datetime, datetime.date)):
             clean[k] = v.strftime("%Y-%m-%d")
        else:
             clean[k] = v
    return clean

def get_data(api_url):
    try:
        r = requests.get(f"{api_url}/data", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if not data:
                return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])
            return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
    return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])

def get_logs(api_url):
    try:
        r = requests.get(f"{api_url}/logs", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return pd.DataFrame(data)
    except:
        pass
    return pd.DataFrame()

app_mode = st.sidebar.selectbox("Pilih Aplikasi", ["📝 Input & Scraping", "🔄 Translator"])

# --- Job Polling Widget ---
def job_polling_widget():
    if st.session_state.job_id:
        st.divider()
        st.info(f"⏳ Background Job Running (ID: {st.session_state.job_id})...")

        try:
            r = requests.get(f"{api_url}/job/{st.session_state.job_id}", timeout=3)
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
                current_action = job_data.get("current_action", "")
                if current_action:
                    st.text(f"Status: {current_action}")

                # Update live results to session state
                if results:
                    df_res = pd.DataFrame(results)
                    if st.session_state.job_type == "batch":
                        st.session_state.batch_results = df_res
                    elif st.session_state.job_type == "gap":
                        st.session_state.gap_results = df_res

                if status == "completed":
                    if not results:
                        st.warning("Job Completed: No articles found.")
                    else:
                        st.success(f"Job Completed! Found {len(results)} articles.")

                    st.session_state.job_id = None
                    st.session_state.job_type = None
                    time.sleep(1)
                    st.rerun()
                elif status == "failed":
                    st.error(f"Job Failed: {job_data.get('msg')}")
                    st.session_state.job_id = None
                    st.session_state.job_type = None
                else:
                    # Still running, refresh less frequently to allow multitasking
                    time.sleep(5)
                    st.rerun()
            else:
                st.warning("Job status check failed (Backend busy?)")
        except Exception as e:
            # Don't crash on transient connection errors
            st.caption(f"Waiting for connection... ({e})")
            time.sleep(5)
            st.rerun()

# --- Calendar Helper ---
def render_calendar(year, month, df_data, df_logs, entity):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    st.write(f"#### 📅 Status: {month_name} {year}")

    # Filter data for this month/year/entity
    if not df_data.empty and 'Tanggal' in df_data.columns:
        df_data['Tanggal'] = pd.to_datetime(df_data['Tanggal'], errors='coerce', dayfirst=True)
        mask_data = (df_data['Tanggal'].dt.year == year) & \
                    (df_data['Tanggal'].dt.month == month) & \
                    (df_data['Entitas'] == entity)
        filled_dates = set(df_data[mask_data]['Tanggal'].dt.day.astype(int).tolist())
    else:
        filled_dates = set()

    # Filter logs
    skipped_dates = set()
    if not df_logs.empty and 'Tanggal' in df_logs.columns:
         df_logs['Tanggal'] = pd.to_datetime(df_logs['Tanggal'], errors='coerce', dayfirst=True)
         mask_logs = (df_logs['Tanggal'].dt.year == year) & \
                     (df_logs['Tanggal'].dt.month == month) & \
                     (df_logs['Entitas'] == entity)
         skipped_dates = set(df_logs[mask_logs]['Tanggal'].dt.day.astype(int).tolist())

    # Draw Calendar Grid
    cols = st.columns(7)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, d in enumerate(days):
        cols[i].write(f"**{d}**")

    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write(" ")
            else:
                status_icon = "⬜" # Default Empty
                if day in filled_dates:
                    status_icon = "✅" # Filled
                elif day in skipped_dates:
                    status_icon = "🟨" # Skipped
                else:
                    status_icon = "🟥" # Empty/Missing

                cols[i].write(f"{day} {status_icon}")

# ==========================================
# APP A: INPUT & SCRAPING
# ==========================================
if app_mode == "📝 Input & Scraping":
    st.title("📝 Input & Scraping Dashboard")
    
    sub_page = st.sidebar.radio("Menu", ["Input Manual", "Batch Scrape (Auto)", "Gap Filler (Manual Scrape)", "Monitor Data"])

    # Global Job Status
    job_polling_widget()

    # --- 1. INPUT MANUAL (ENHANCED) ---
    if sub_page == "Input Manual":
        st.subheader("Input Berita Manual")

        # Selectors
        c_sel1, c_sel2, c_sel3 = st.columns(3)
        sel_year = c_sel1.number_input("Year", min_value=2000, max_value=2030, value=datetime.now().year)
        sel_month = c_sel2.selectbox("Month", range(1, 13), index=datetime.now().month - 1)
        sel_entity = c_sel3.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"])

        # Load Data
        df = get_data(api_url)
        logs = get_logs(api_url)

        # Render Calendar
        try:
            render_calendar(sel_year, sel_month, df, logs, sel_entity)
        except Exception as e:
            st.error(f"Calendar Error: {e}")
        st.divider()

        # Date Selection
        c1, c2 = st.columns([1, 2])
        with c1:
            st.write("### 📆 Select Date to Edit")
            # Default to today if in range, else 1st of selected month
            default_date = datetime(sel_year, sel_month, 1)
            today = datetime.now()
            if today.year == sel_year and today.month == sel_month:
                default_date = today

            selected_date = st.date_input("Pick a Date", value=default_date, key="input_manual_date")

            # Check Status
            date_str = str(selected_date)

            # Check existing data
            is_filled = False
            if not df.empty and 'Tanggal' in df.columns:
                # Re-convert if needed or just string match
                existing = df[(df['Tanggal'].astype(str).str.startswith(date_str)) & (df['Entitas'] == sel_entity)]
                is_filled = not existing.empty

            # Check skipped
            is_skipped = False
            if not logs.empty and 'Tanggal' in logs.columns:
                skipped_log = logs[(logs['Tanggal'].astype(str).str.startswith(date_str)) & (logs['Entitas'] == sel_entity)]
                is_skipped = not skipped_log.empty

            st.write(f"**Status for {date_str}:**")
            if is_filled:
                st.success(f"✅ Data Found ({len(existing) if is_filled else 0} articles)")
            elif is_skipped:
                st.warning("🟨 Marked as Skipped/No News")
            else:
                st.error("🟥 No Data (Empty)")

            # Actions for Empty/Skipped
            if not is_filled:
                st.markdown("---")
                st.write("**Quick Actions:**")
                if st.button("🚫 Mark as No News / Pass"):
                    try:
                        r = requests.post(f"{api_url}/log_empty", json={"date": date_str, "entity": sel_entity, "reason": "Manual Pass"})
                        if r.status_code == 200:
                            st.success("Marked as Skipped!")
                            time.sleep(1)
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

                st.markdown("---")
                st.write("**Find News Links:**")
                search_kw = st.text_input("Search Keywords", value="news berita terkini")
                if st.button("🔎 Search Links"):
                    with st.spinner("Searching..."):
                        try:
                            payload = {"date": date_str, "entity": sel_entity, "keywords": search_kw}
                            r = requests.post(f"{api_url}/search_links", json=payload)
                            if r.status_code == 200:
                                links = r.json()
                                if links:
                                    st.write(f"Found {len(links)} links:")
                                    for l in links:
                                        link_url = l.get('url')
                                        link_title = l.get('title')
                                        st.markdown(f"- [{link_title}]({link_url})")
                                        st.code(link_url) # Easy copy
                                else:
                                    st.info("No links found.")
                        except Exception as e:
                            st.error(f"Search Error: {e}")

        with c2:
            st.write("### 📝 Editor / Scraper")

            # Helper to Scrape from URL
            with st.expander("🌐 Scrape from URL (Auto-Fill)"):
                st.caption(f"Scraping will fill title/content but keep the date as **{selected_date}**")
                url_to_scrape = st.text_input("Paste URL here")
                if st.button("🚀 Scrape URL"):
                     if url_to_scrape:
                         with st.spinner("Scraping..."):
                             try:
                                 r = requests.post(f"{api_url}/scrape_url", json={"url": url_to_scrape})
                                 if r.status_code == 200:
                                     scraped_data = r.json()
                                     st.session_state['temp_title'] = scraped_data.get('Judul', '')
                                     st.session_state['temp_content'] = scraped_data.get('Isi', '')
                                     st.session_state['temp_url'] = url_to_scrape

                                     # Update Date if found
                                     scraped_date_str = scraped_data.get('Tanggal')
                                     if scraped_date_str:
                                         try:
                                             # Assuming backend returns YYYY-MM-DD or standard iso format
                                             new_date = datetime.strptime(str(scraped_date_str), "%Y-%m-%d").date()
                                             st.session_state['input_manual_date'] = new_date
                                             st.success(f"Scraped! Date updated to {new_date}.")
                                             time.sleep(0.5)
                                             st.rerun()
                                         except:
                                             st.warning("Scraped content, but could not parse date.")
                                     else:
                                         st.success("Scraped! Form updated below.")
                                 else:
                                     st.error(f"Failed: {r.text}")
                             except Exception as e:
                                 st.error(f"Error: {e}")

            # Form
            with st.form("manual_form"):
                # Use session state for pre-filling if available
                default_title = st.session_state.get('temp_title', '')
                default_content = st.session_state.get('temp_content', '')
                default_url = st.session_state.get('temp_url', '')

                # Clear temp state after use to avoid sticking
                if 'temp_title' in st.session_state: del st.session_state['temp_title']
                if 'temp_content' in st.session_state: del st.session_state['temp_content']
                if 'temp_url' in st.session_state: del st.session_state['temp_url']

                t = st.text_input("Judul", value=default_title)
                c = st.text_area("Isi", height=300, value=default_content)
                u = st.text_input("URL (Optional)", value=default_url)

                if st.form_submit_button("💾 Simpan Data"):
                    payload = {
                        "Tanggal": str(selected_date),
                        "Entitas": sel_entity,
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
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(r.text)
                    except Exception as e:
                        st.error(f"Backend Error at {api_url}: {e}")

            # Show existing data for this date below form
            if is_filled:
                st.write("---")
                st.write("#### Existing Data for this Date:")
                if not existing.empty:
                     st.dataframe(existing[["Judul", "URL"]])


    # --- 2. BATCH SCRAPE ---
    elif sub_page == "Batch Scrape (Auto)":
        st.subheader("🚀 Batch Scrape (Async)")
        c1, c2, c3 = st.columns(3)
        start = c1.date_input("Start")
        end = c2.date_input("End")
        entity = c3.selectbox("Entity", ["AirAsia", "Garuda Indonesia"], key="batch_ent")
        kw = st.text_input("Keywords")
        
        if st.button("Start Batch Scrape", disabled=(st.session_state.job_id is not None)):
            if start > end:
                st.error("Error: Start Date must be before or equal to End Date.")
            else:
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
                        clean_payload = serialize_payload(payload)
                        try:
                            requests.post(f"{api_url}/save", json=clean_payload)
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
            if start_gap > end_gap:
                st.error("Error: Start Date must be before or equal to End Date.")
            else:
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
                        clean_payload = serialize_payload(payload)
                        try:
                            requests.post(f"{api_url}/save", json=clean_payload)
                            count += 1
                        except Exception as e:
                            st.error(f"Save error: {e}")
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
                df["Tanggal"] = pd.to_datetime(df["Tanggal"], errors='coerce', dayfirst=True)

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
