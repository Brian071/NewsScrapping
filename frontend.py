import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import time
import calendar
import asyncio
import nest_asyncio
import uuid

# Local Modules
import db_handler
import gsheet_handler
import translator_utils

# Force default loop policy for Colab stability
try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except Exception:
    pass

try:
    nest_asyncio.apply()
except Exception:
    pass

# Initialize DB on Startup
db_handler.init_db()

st.set_page_config(page_title="Auto AI News System", page_icon="🤖", layout="wide")

# --- Session State Initialization ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = pd.DataFrame()
if 'gap_results' not in st.session_state:
    st.session_state.gap_results = pd.DataFrame()
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'scrape_url_result' not in st.session_state:
    st.session_state.scrape_url_result = None

if 'job_id' not in st.session_state:
    st.session_state.job_id = None
if 'job_type' not in st.session_state:
    # 'batch', 'gap', 'search_links', 'scrape_url'
    st.session_state.job_type = None

# --- Sidebar Config ---
st.sidebar.title("🤖 Auto AI System")
st.sidebar.header("⚙️ Configuration")
st.sidebar.info("Running in Database Mode (Worker Driven)")

# --- Helper Functions ---
def serialize_payload(payload):
    """Ensure all values in payload are JSON serializable (convert timestamps to str)."""
    clean = {}
    for k, v in payload.items():
        if isinstance(v, (pd.Timestamp, datetime, datetime.date)):
             clean[k] = v.strftime("%Y-%m-%d")
        else:
             clean[k] = v
    return clean

def get_data():
    try:
        df = gsheet_handler.read_sheet_to_df(worksheet_name="data_berita")
        if df.empty:
             return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])
        return df
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])

def get_logs():
    try:
        return gsheet_handler.get_empty_logs()
    except:
        pass
    return pd.DataFrame()

# --- Job Polling Widget ---
def job_polling_widget():
    if st.session_state.job_id:
        st.divider()
        st.info(f"⏳ Background Job Running (ID: {st.session_state.job_id})...")

        try:
            # Poll DB directly
            job = db_handler.get_job(st.session_state.job_id)
            if job:
                status = job.get("status")
                processed = job.get("processed", 0)
                total = job.get("total", 1)

                # Fetch results if any
                results = db_handler.get_job_results(st.session_state.job_id)

                # Progress Bar
                if total > 0:
                     progress = min(1.0, max(0.0, processed / total))
                     st.progress(progress)
                else:
                     st.progress(0) # Show 0% if total is 0 (Initializing)

                st.write(f"Processed: {processed} / {total}")

                current_action = job.get("current_action", "")
                if current_action:
                    st.text(f"Status: {current_action}")

                if status == "completed":
                    # Distribute results based on job type
                    if st.session_state.job_type == "batch":
                        st.session_state.batch_results = pd.DataFrame(results)
                        st.success(f"Job Completed! Found {len(results)} articles.")

                    elif st.session_state.job_type == "gap":
                        st.session_state.gap_results = pd.DataFrame(results)
                        st.success(f"Job Completed! Found {len(results)} articles.")

                    elif st.session_state.job_type == "search_links":
                        # Convert results to list of dicts for display
                        st.session_state.search_results = results
                        st.success(f"Search Completed! Found {len(results)} links.")

                    elif st.session_state.job_type == "scrape_url":
                        if results:
                            st.session_state.scrape_url_result = results[0]
                            st.success("URL Scraped successfully!")
                        else:
                            st.error("URL Scraped but no result returned?")

                    st.session_state.job_id = None
                    st.session_state.job_type = None
                    time.sleep(1)
                    st.rerun()

                elif status == "failed":
                    st.error(f"Job Failed: {job.get('msg')}")
                    st.session_state.job_id = None
                    st.session_state.job_type = None
                else:
                    time.sleep(2)
                    st.rerun()
            else:
                st.warning("Job not found in DB...")
                time.sleep(2)
        except Exception as e:
             st.error(f"Polling Error: {e}")
             time.sleep(5)
             st.rerun()

app_mode = st.sidebar.selectbox("Pilih Aplikasi", ["📝 Input & Scraping", "🔄 Translator"])

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

        c_sel1, c_sel2, c_sel3 = st.columns(3)
        sel_year = c_sel1.number_input("Year", min_value=2000, max_value=2030, value=datetime.now().year)
        sel_month = c_sel2.selectbox("Month", range(1, 13), index=datetime.now().month - 1)
        sel_entity = c_sel3.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"])

        df = get_data()
        logs = get_logs()

        # Render Calendar
        def render_calendar(year, month, df_data, df_logs, entity):
            cal = calendar.monthcalendar(year, month)
            month_name = calendar.month_name[month]
            st.write(f"#### 📅 Status: {month_name} {year}")

            if not df_data.empty and 'Tanggal' in df_data.columns:
                df_data['Tanggal'] = pd.to_datetime(df_data['Tanggal'], errors='coerce', dayfirst=True)
                mask_data = (df_data['Tanggal'].dt.year == year) & \
                            (df_data['Tanggal'].dt.month == month) & \
                            (df_data['Entitas'] == entity)
                filled_dates = set(df_data[mask_data]['Tanggal'].dt.day.astype(int).tolist())
            else:
                filled_dates = set()

            if not df_logs.empty and 'Tanggal' in df_logs.columns:
                 df_logs['Tanggal'] = pd.to_datetime(df_logs['Tanggal'], errors='coerce', dayfirst=True)
                 mask_logs = (df_logs['Tanggal'].dt.year == year) & \
                             (df_logs['Tanggal'].dt.month == month) & \
                             (df_logs['Entitas'] == entity)
                 skipped_dates = set(df_logs[mask_logs]['Tanggal'].dt.day.astype(int).tolist())

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
                        status_icon = "⬜"
                        if day in filled_dates: status_icon = "✅"
                        elif day in skipped_dates: status_icon = "🟨"
                        else: status_icon = "🟥"
                        cols[i].write(f"{day} {status_icon}")

        try:
            render_calendar(sel_year, sel_month, df, logs, sel_entity)
        except Exception as e:
            st.error(f"Calendar Error: {e}")
        st.divider()

        # Date Selection
        c1, c2 = st.columns([1, 2])
        with c1:
            st.write("### 📆 Select Date to Edit")
            default_date = datetime(sel_year, sel_month, 1)
            today = datetime.now()
            if today.year == sel_year and today.month == sel_month:
                default_date = today

            selected_date = st.date_input("Pick a Date", value=default_date, key="input_manual_date")
            date_str = str(selected_date)

            # Check Status
            is_filled = False
            existing = pd.DataFrame()
            if not df.empty and 'Tanggal' in df.columns:
                 # Ensure string matching works
                 df['Tanggal_Str'] = df['Tanggal'].astype(str)
                 existing = df[(df['Tanggal_Str'].str.contains(date_str)) & (df['Entitas'] == sel_entity)]
                 is_filled = not existing.empty

            is_skipped = False
            if not logs.empty and 'Tanggal' in logs.columns:
                logs['Tanggal_Str'] = logs['Tanggal'].astype(str)
                skipped_log = logs[(logs['Tanggal_Str'].str.contains(date_str)) & (logs['Entitas'] == sel_entity)]
                is_skipped = not skipped_log.empty

            st.write(f"**Status for {date_str}:**")
            if is_filled:
                st.success(f"✅ Data Found ({len(existing)} articles)")
            elif is_skipped:
                st.warning("🟨 Marked as Skipped/No News")
            else:
                st.error("🟥 No Data (Empty)")

            # Actions
            if not is_filled:
                st.markdown("---")
                st.write("**Quick Actions:**")
                if st.button("🚫 Mark as No News / Pass"):
                    try:
                        gsheet_handler.log_empty_date(date_str, sel_entity, "Manual Pass")
                        st.success("Marked as Skipped!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

                st.markdown("---")
                st.write("**Find News Links:**")
                search_kw = st.text_input("Search Keywords", value="news berita terkini")

                if st.button("🔎 Search Links", disabled=(st.session_state.job_id is not None)):
                    # Clear previous results
                    st.session_state.search_results = []

                    # Create Search Job
                    job_id = str(uuid.uuid4())
                    db_handler.create_job(job_id, "queued")
                    db_handler.save_job_params(job_id, {
                        "job_type": "search_links",
                        "date": date_str,
                        "entity": sel_entity,
                        "keywords": search_kw
                    })
                    st.session_state.job_id = job_id
                    st.session_state.job_type = "search_links"
                    st.rerun()

                # Display Search Results if available
                if st.session_state.search_results:
                     st.write(f"Found {len(st.session_state.search_results)} links:")
                     for item in st.session_state.search_results:
                         title = item.get('Judul', 'No Title') # 'title' mapped to 'Judul' in get_job_results
                         url = item.get('URL')
                         st.markdown(f"- [{title}]({url})")
                         st.code(url)

        with c2:
            st.write("### 📝 Editor / Scraper")

            with st.expander("🌐 Scrape from URL (Auto-Fill)"):
                st.caption("Scraping will fill title/content. Date updated if detected.")
                url_to_scrape = st.text_input("Paste URL here")

                if st.button("🚀 Scrape URL", disabled=(st.session_state.job_id is not None)):
                    if url_to_scrape:
                        st.session_state.scrape_url_result = None

                        job_id = str(uuid.uuid4())
                        db_handler.create_job(job_id, "queued")
                        db_handler.save_job_params(job_id, {
                            "job_type": "scrape_url",
                            "url": url_to_scrape
                        })
                        st.session_state.job_id = job_id
                        st.session_state.job_type = "scrape_url"
                        st.rerun()

            # Check for Scrape Result
            if st.session_state.scrape_url_result:
                res = st.session_state.scrape_url_result
                st.session_state['temp_title'] = res.get('Judul', '')
                st.session_state['temp_content'] = res.get('Isi', '')
                st.session_state['temp_url'] = res.get('URL', '')

                # Check date
                s_date = res.get('Tanggal')
                if s_date:
                     try:
                         new_date = datetime.strptime(str(s_date), "%Y-%m-%d").date()
                         st.session_state['input_manual_date'] = new_date
                         st.success(f"Date detected: {new_date}")
                     except:
                         pass

                # Clear result after consuming
                st.session_state.scrape_url_result = None
                st.rerun()

            with st.form("manual_form"):
                default_title = st.session_state.get('temp_title', '')
                default_content = st.session_state.get('temp_content', '')
                default_url = st.session_state.get('temp_url', '')

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
                        gsheet_handler.append_to_sheet(payload)
                        st.success("Tersimpan!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Save Error: {e}")

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
                st.error("Start Date must be before End Date.")
            else:
                job_id = str(uuid.uuid4())
                db_handler.create_job(job_id, "queued")
                db_handler.save_job_params(job_id, {
                    "job_type": "batch_scrape",
                    "start_date": str(start),
                    "end_date": str(end),
                    "entity": entity,
                    "keywords": kw
                })
                st.session_state.job_id = job_id
                st.session_state.job_type = "batch"
                st.rerun()

        if not st.session_state.batch_results.empty:
            st.divider()
            st.write(f"### 📥 Scraped Results ({len(st.session_state.batch_results)})")

            if st.button("🗑️ Clear Results"):
                st.session_state.batch_results = pd.DataFrame()
                st.rerun()

            edited = st.data_editor(st.session_state.batch_results, key="batch_editor")

            # Note: Batch scrape worker ALREADY saves to DB/Sheet?
            # In api.py run_scrape_job, it saves to DB AND Syncs to Drive.
            # So the results in `batch_results` are ALREADY saved.
            # But the user might want to edit them?
            # If they are already synced, editing here won't update the sheet unless we implement update logic.
            # The previous logic was: Frontend receives results, then User selects "Save".
            # BUT api.py logic was: Worker saves immediately.
            # Wait, `api.py` run_scrape_job says:
            # `db_handler.save_result` (Local DB)
            # Then `Syncing to Drive...` (GSheet)
            # So they ARE already in GSheet.
            # So "Save Selected Results" button in previous code was... redundant?
            # Or maybe previous code didn't sync automatically?
            # Looking at `api.py` `run_scrape_job`: It DOES call `gsheet_handler.bulk_append`.
            # So yes, they are autosaved.
            # The previous Frontend had "Save Selected Results" which called `/save`.
            # If `run_scrape_job` already saved them, this would create duplicates!
            # Let's check `api.py` again.
            # `run_scrape_job` -> `gsheet_handler.bulk_append`.
            # `frontend.py` -> `requests.post(..., /start_scrape)`.
            # Then it just DISPLAYS results.
            # The previous frontend `Batch Scrape` section had `st.data_editor` and `Save Selected Results`.
            # If the user clicked Save, it would POST `/save`.
            # This implies the previous `start_scrape` MIGHT NOT have been syncing to GSheet?
            # In `api.py`: `run_scrape_job` DOES sync.
            # So the previous frontend was likely creating duplicates if the user clicked Save.
            # OR the user requested "if data exists... don't show".

            # Clarification: User said "kalau data sudah ada di dataset jangan lagi ditampilkan".
            # This implies Deduplication.
            # `worker.py` (and `api.py`) has deduplication logic BEFORE saving.

            # So, if `worker.py` autosaves, we should just show "Results (Saved)" and maybe allow Deletion?
            # Or maybe we should disable autosync in worker and let user Review & Save?
            # The "Gap Filler" mode in `frontend.py` had a "Save Filled Gaps" button.
            # The "Batch Scrape" also had a "Save Selected Results".
            # This suggests the user wants a Review step.

            # BUT, `api.py` was written to autosave.
            # If I want Review step, `worker.py` should save to DB but NOT sync to GSheet until approved.
            # However, `worker.py` calls `gsheet_handler.bulk_append`.

            # To be safe and follow the "Worker replaces API" model exactly:
            # `worker.py` behaves like `api.py`. It syncs.
            # So Frontend just displays "Here is what was scraped and saved."
            # If the user edits it here, they are editing a disconnected dataframe.

            st.info("Results have been automatically saved to the database/sheet.")


    # --- 3. GAP FILLER ---
    elif sub_page == "Gap Filler (Manual Scrape)":
        st.subheader("🕵️ Manual Scrape / Gap Filler")
        c1, c2 = st.columns(2)
        entity_gap = c1.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"], key="gap_ent")
        kw_gap = c2.text_input("Keywords", key="gap_kw")
        start_gap = c1.date_input("Range Start", key="gap_start")
        end_gap = c2.date_input("Range End", key="gap_end")

        if st.button("🔍 Scan & Fill Gaps", disabled=(st.session_state.job_id is not None)):
            if start_gap > end_gap:
                st.error("Start Date must be before End Date.")
            else:
                job_id = str(uuid.uuid4())
                db_handler.create_job(job_id, "queued")
                db_handler.save_job_params(job_id, {
                    "job_type": "batch_scrape", # Gap filler is just batch scrape
                    "start_date": str(start_gap),
                    "end_date": str(end_gap),
                    "entity": entity_gap,
                    "keywords": kw_gap
                })
                st.session_state.job_id = job_id
                st.session_state.job_type = "gap"
                st.rerun()

        if not st.session_state.gap_results.empty:
            st.divider()
            # Client-side deduplication for display
            df_existing = get_data()
            existing_urls = set()
            if not df_existing.empty and 'URL' in df_existing.columns:
                 existing_urls = set(df_existing['URL'].dropna().astype(str).values)

            # Filter
            mask = []
            for _, row in st.session_state.gap_results.iterrows():
                url = row.get('URL')
                if url in existing_urls: mask.append(False)
                else: mask.append(True)

            df_display = st.session_state.gap_results[mask]

            st.write(f"### 📥 Results ({len(df_display)})")
            st.caption("Duplicates hidden.")

            if st.button("🗑️ Clear Results", key="clr_gap"):
                st.session_state.gap_results = pd.DataFrame()
                st.rerun()

            st.data_editor(df_display)
            st.info("Results are automatically saved.")

    # --- 4. MONITOR ---
    elif sub_page == "Monitor Data":
        st.subheader("Data Monitor")
        c1, c2, c3, c4 = st.columns(4)
        m_start = c1.date_input("Start", value=datetime.now() - timedelta(days=30))
        m_end = c2.date_input("End", value=datetime.now())
        m_entity = c3.selectbox("Entity", ["All", "AirAsia", "Garuda Indonesia"])
        if c4.button("Refresh"): st.rerun()

        df = get_data()
        if not df.empty and "Tanggal" in df.columns:
            df["Tanggal"] = pd.to_datetime(df["Tanggal"], errors='coerce', dayfirst=True)
            mask = (df["Tanggal"] >= pd.to_datetime(m_start)) & (df["Tanggal"] <= pd.to_datetime(m_end))
            if m_entity != "All": mask = mask & (df["Entitas"] == m_entity)
            st.dataframe(df[mask].sort_values(by="Tanggal", ascending=False))
        else:
            st.write("No data.")

# ==========================================
# APP B: TRANSLATOR
# ==========================================
elif app_mode == "🔄 Translator":
    st.title("🔄 Auto Translator")
    tab1, tab2 = st.tabs(["Pending", "History"])
    df = get_data()
    
    with tab1:
        if not df.empty and 'Judul_Inggris' in df.columns:
            mask = (df['Judul_Inggris'] == "") | (df['Isi_Inggris'] == "") | (df['Judul_Inggris'].isnull())
            pending = df[mask].copy()
            pending["Pilih"] = True

            st.info(f"Pending: {len(pending)}")
            edited = st.data_editor(pending)

            if st.button("Translate Selected"):
                to_proc = edited[edited["Pilih"] == True]
                if not to_proc.empty:
                    with st.spinner("Translating... (This uses local CPU/GPU)"):
                        # Use translator_utils directly
                        translator_utils.load_model()
                        splitter = translator_utils.get_splitter()

                        count = 0
                        for idx, row in to_proc.iterrows():
                            # We need to update GSheet.
                            # We have to be careful about matching the row.
                            # We assume Date+Entity+Title is unique key?
                            # Or just use row index if we are careful?
                            # GSheet handler update_row_in_sheet uses (date, entity, old_title).

                            old_title = row['Judul']
                            j_ing = row['Judul_Inggris']
                            i_ing = row['Isi_Inggris']

                            updated = {}
                            if not j_ing:
                                j_ing = translator_utils.smart_translate(old_title)
                                updated['Judul_Inggris'] = j_ing
                            if not i_ing:
                                i_ing = translator_utils.smart_translate(row['Isi'])
                                updated['Isi_Inggris'] = i_ing

                            if updated:
                                try:
                                    gsheet_handler.update_row_in_sheet(
                                        row['Tanggal'],
                                        row['Entitas'],
                                        old_title,
                                        updated
                                    )
                                    count += 1
                                except Exception as e:
                                    st.error(f"Failed to update {old_title}: {e}")

                        st.success(f"Translated {count} articles.")
                        time.sleep(1)
                        st.rerun()

    with tab2:
        if not df.empty and 'Judul_Inggris' in df.columns:
            st.dataframe(df[df['Judul_Inggris'] != ""])
