import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import time
import calendar
import asyncio
import nest_asyncio
import uuid

# Local Modules
import gsheet_handler
import translator_utils
import scraper_lib
import config # Load configuration

# Force default loop policy for Colab stability
try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except Exception:
    pass

try:
    nest_asyncio.apply()
except Exception:
    pass

st.set_page_config(page_title="Auto AI News System", page_icon="🤖", layout="wide")

# --- Sidebar Config ---
st.sidebar.title("🤖 Auto AI System")
st.sidebar.header("⚙️ Configuration")
st.sidebar.info("Running in Direct Mode (Synchronous)")

# --- Session State ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = pd.DataFrame()
if 'gap_results' not in st.session_state:
    st.session_state.gap_results = pd.DataFrame()

# Import JSON/OS here if not already imported (but python handles duplicate imports)
import json
import os

# Check for temp results on load
TEMP_RESULTS_FILE = "temp_scrape_results.json"

if os.path.exists(TEMP_RESULTS_FILE) and st.session_state.batch_results.empty:
    try:
        data = []
        with open(TEMP_RESULTS_FILE, "r") as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
        if data:
            st.session_state.batch_results = pd.DataFrame(data)
            st.toast(f"Restored {len(data)} items from previous session.")
    except Exception as e:
        print(f"Failed to load temp results: {e}")

# --- Helper Functions ---
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

app_mode = st.sidebar.selectbox("Pilih Aplikasi", ["📝 Input & Scraping", "🔄 Translator"])

# ==========================================
# APP A: INPUT & SCRAPING
# ==========================================
if app_mode == "📝 Input & Scraping":
    st.title("📝 Input & Scraping Dashboard")
    
    sub_page = st.sidebar.radio("Menu", ["Input Manual", "Batch Scrape (Auto)", "Gap Filler (Manual Scrape)", "Monitor Data", "Troubleshoot Connection"])

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
                # Robust filtering: Strip whitespace from Entity
                mask_data = (df_data['Tanggal'].dt.year == year) & \
                            (df_data['Tanggal'].dt.month == month) & \
                            (df_data['Entitas'].astype(str).str.strip() == entity)
                filled_dates = set(df_data[mask_data]['Tanggal'].dt.day.astype(int).tolist())
            else:
                filled_dates = set()

            skipped_dates = set()
            if not df_logs.empty and 'Tanggal' in df_logs.columns:
                 df_logs['Tanggal'] = pd.to_datetime(df_logs['Tanggal'], errors='coerce', dayfirst=True)
                 # Check entity matching more robustly (strip whitespace)
                 mask_logs = (df_logs['Tanggal'].dt.year == year) & \
                             (df_logs['Tanggal'].dt.month == month) & \
                             (df_logs['Entitas'].astype(str).str.strip() == entity)
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
                 df['Tanggal_Str'] = df['Tanggal'].astype(str)
                 # Robust check: Strip entity
                 existing = df[(df['Tanggal_Str'].str.contains(date_str)) & (df['Entitas'].astype(str).str.strip() == sel_entity)]
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

                if st.button("🔎 Search Links"):
                    with st.spinner("Searching..."):
                        links = asyncio.run(scraper_lib.run_search_links(date_str, sel_entity, search_kw))
                        st.session_state.search_results = links
                        if links:
                             st.success(f"Found {len(links)} links")
                        else:
                             st.warning("No links found.")

                if 'search_results' in st.session_state and st.session_state.search_results:
                     st.write(f"Found {len(st.session_state.search_results)} links:")

                     df_search = pd.DataFrame(st.session_state.search_results)
                     if "Block" not in df_search.columns:
                         df_search.insert(0, "Block", False)

                     # Show editor
                     edited_search = st.data_editor(
                         df_search,
                         column_config={
                             "url": st.column_config.LinkColumn("URL"),
                             "Block": st.column_config.CheckboxColumn("Block", default=False)
                         },
                         key="manual_search_editor",
                         num_rows="dynamic"
                     )

                     if st.button("🚫 Block Selected", key="manual_block_btn"):
                         to_block = edited_search[edited_search["Block"] == True]
                         if not to_block.empty:
                             with st.spinner("Blocking..."):
                                 for _, row in to_block.iterrows():
                                     gsheet_handler.log_blocked_content(row.get("url"), row.get("title"), "Manual Block (Search)")

                                 # Update session state: keep only unblocked
                                 remaining_df = edited_search[edited_search["Block"] == False]
                                 if "Block" in remaining_df.columns:
                                     remaining_df = remaining_df.drop(columns=["Block"])

                                 st.session_state.search_results = remaining_df.to_dict('records')
                                 st.success("Blocked!")
                                 time.sleep(1)
                                 st.rerun()

        with c2:
            st.write("### 📝 Editor / Scraper")

            with st.expander("🌐 Scrape from URL (Auto-Fill)"):
                url_to_scrape = st.text_input("Paste URL here")
                if st.button("🚀 Scrape URL"):
                    if url_to_scrape:
                        with st.spinner("Scraping..."):
                            t, c, d = asyncio.run(scraper_lib.extract_article_content_async(url_to_scrape))
                            if t and t != "Error":
                                # Update session state keys directly used by the inputs
                                st.session_state['input_judul'] = t
                                st.session_state['input_isi'] = c
                                st.session_state['input_url'] = url_to_scrape

                                if d:
                                     try:
                                         new_date = datetime.strptime(str(d), "%Y-%m-%d").date()
                                         st.session_state['input_manual_date'] = new_date
                                         st.success(f"Date detected: {new_date}")
                                     except: pass
                                st.rerun()
                            else:
                                st.error(f"Failed: {c}")

            # Initialize input keys if not present
            if 'input_judul' not in st.session_state: st.session_state['input_judul'] = ""
            if 'input_isi' not in st.session_state: st.session_state['input_isi'] = ""
            if 'input_url' not in st.session_state: st.session_state['input_url'] = ""

            with st.form("manual_form"):
                # Use key= to bind directly to session state
                t = st.text_input("Judul", key="input_judul")
                c = st.text_area("Isi", height=300, key="input_isi")
                u = st.text_input("URL (Optional)", key="input_url")

                if st.form_submit_button("💾 Simpan Data"):
                    # Read values directly from session state to ensure latest user edits are captured
                    # (Variables t, c, u are also valid here, but explicit state read is safer with forms on some versions)
                    final_t = st.session_state.get("input_judul", "")
                    final_c = st.session_state.get("input_isi", "")
                    final_u = st.session_state.get("input_url", "")

                    if not final_t:
                        st.error("Judul cannot be empty.")
                    else:
                        payload = {
                            "Tanggal": str(selected_date),
                            "Entitas": sel_entity,
                            "Judul": final_t,
                            "Isi": final_c,
                            "URL": final_u,
                            "Judul_Inggris": "",
                            "Isi_Inggris": ""
                        }
                        try:
                            gsheet_handler.append_to_sheet(payload)
                            st.success("Tersimpan!")

                            # Clear inputs after save
                            st.session_state['input_judul'] = ""
                            st.session_state['input_isi'] = ""
                            st.session_state['input_url'] = ""

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
        st.subheader("🚀 Batch Scrape (Direct)")
        c1, c2, c3 = st.columns(3)
        start = c1.date_input("Start")
        end = c2.date_input("End")
        entity = c3.selectbox("Entity", ["AirAsia", "Garuda Indonesia"], key="batch_ent")
        
        c4, c5 = st.columns(2)
        kw = c4.text_input("Keywords")
        region = c5.selectbox("Search Region", ["wt-wt (Global)", "id-id (Indonesia)"], index=0)

        status_box = st.empty()
        progress_bar = st.empty()

        if st.button("Start Batch Scrape"):
            if start > end:
                st.error("Start Date must be before End Date.")
            else:
                progress_bar.progress(0)

                # Callback wrapper to handle UI updates safely
                def update_progress(current, total, msg):
                    status_box.markdown(f"**{msg}**") # Markdown for bold warnings
                    if total > 0:
                        progress_bar.progress(min(1.0, current/total))

                # Extract region code
                reg_code = region.split(" ")[0]
                results = asyncio.run(scraper_lib.run_batch_scrape(
                    str(start), str(end), entity, kw, update_progress, region=reg_code
                ))

                if results:
                    st.session_state.batch_results = pd.DataFrame(results)
                    st.success(f"Finished! Found {len(results)} articles.")
                else:
                    st.warning("Finished, but no new articles found.")

        if not st.session_state.batch_results.empty:
            st.divider()
            st.write(f"### 📥 Review Results ({len(st.session_state.batch_results)})")

            # Add Block Column if missing
            if "Block" not in st.session_state.batch_results.columns:
                st.session_state.batch_results.insert(0, "Block", False)

            c_clear, c_block, c_save = st.columns([1, 1, 2])

            if c_clear.button("🗑️ Clear Results"):
                st.session_state.batch_results = pd.DataFrame()
                if os.path.exists(TEMP_RESULTS_FILE):
                    os.remove(TEMP_RESULTS_FILE)
                st.rerun()

            # Editor
            edited_df = st.data_editor(st.session_state.batch_results, num_rows="dynamic", key="batch_editor")

            # Block Button
            if c_block.button("🚫 Block Selected"):
                to_block = edited_df[edited_df["Block"] == True]
                if not to_block.empty:
                    with st.spinner(f"Blocking {len(to_block)} items..."):
                        for _, row in to_block.iterrows():
                             gsheet_handler.log_blocked_content(row.get("URL", ""), row.get("Judul", ""), "Manual Block")

                        # Remove blocked from session state and drop Block column for clean storage
                        remaining = edited_df[edited_df["Block"] == False].copy()
                        if "Block" in remaining.columns:
                            remaining = remaining.drop(columns=["Block"])

                        st.session_state.batch_results = remaining

                        # Update temp file
                        try:
                            if os.path.exists(TEMP_RESULTS_FILE):
                                os.remove(TEMP_RESULTS_FILE)
                            if not remaining.empty:
                                with open(TEMP_RESULTS_FILE, "w") as f:
                                    for _, row in remaining.iterrows():
                                        f.write(json.dumps(row.to_dict()) + "\n")
                        except: pass

                        st.success(f"Blocked {len(to_block)} items.")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.warning("No items selected to block.")

            # Save Button (Manual)
            if c_save.button("💾 Save Verified to Sheet"):
                # Filter out Block=True rows just in case
                save_df = edited_df[edited_df["Block"] == False]

                if not save_df.empty:
                    with st.spinner("Saving to Google Sheets..."):
                        count = 0
                        last_sheet_name = "Unknown"
                        last_saved_title = ""

                        for index, row in save_df.iterrows():
                            # Only save if title exists (basic validation)
                            if row.get("Judul"):
                                try:
                                    # Strict String Conversion
                                    # Remove 'Block' column if present in payload
                                    row_dict = row.to_dict()
                                    if "Block" in row_dict: del row_dict["Block"]

                                    payload = {k: str(v).strip() if v is not None else "" for k, v in row_dict.items()}

                                    # Append and get sheet name
                                    status_str = gsheet_handler.append_to_sheet(payload)

                                    # Parse real sheet name from status string "SheetName (Row X)"
                                    if " (" in status_str:
                                        last_sheet_name = status_str.rsplit(" (", 1)[0]
                                    else:
                                        last_sheet_name = status_str

                                    last_saved_title = payload.get("Judul")
                                    count += 1

                                    # Feedback per row
                                    st.toast(f"Saved: {status_str}")
                                except Exception as e:
                                    st.error(f"Error saving row {index}: {e}")

                        if count > 0:
                            st.success(f"Successfully saved {count} rows! Last location: '{last_sheet_name}'")

                            # Strict Verification
                            try:
                                time.sleep(1.5) # Wait for API propagation
                                df_verify = gsheet_handler.read_sheet_to_df(worksheet_name=last_sheet_name)

                                if not df_verify.empty:
                                    # Check if the LAST saved title is actually present in the last 10 rows
                                    recent_titles = df_verify.tail(10)["Judul"].astype(str).tolist()

                                    if last_saved_title in recent_titles:
                                        st.success(f"✅ Verified: '{last_saved_title}' found in sheet.")
                                    else:
                                        st.error(f"❌ Verification FAILED: '{last_saved_title}' NOT found in last 10 rows of '{last_sheet_name}'.")
                                        st.write(f"Sheet Headers Detected: {df_verify.columns.tolist()}")
                                        st.write("Recent rows found:", recent_titles)
                                        st.warning("Possible Cause: Sheet headers might have spaces/typos, or data was saved to a different sheet.")
                                else:
                                    st.warning("Verification Warning: Sheet appears empty after save.")
                            except Exception as e:
                                st.error(f"Verification Check Failed: {e}")
                        else:
                             st.warning("No valid rows saved.")

                        time.sleep(2)
                else:
                    st.warning("No data to save.")

    # --- 3. GAP FILLER ---
    elif sub_page == "Gap Filler (Manual Scrape)":
        st.subheader("🕵️ Manual Scrape / Gap Filler")
        c1, c2 = st.columns(2)
        entity_gap = c1.selectbox("Entitas", ["AirAsia", "Garuda Indonesia"], key="gap_ent")
        kw_gap = c2.text_input("Keywords", key="gap_kw")
        start_gap = c1.date_input("Range Start", key="gap_start")
        end_gap = c2.date_input("Range End", key="gap_end")

        status_gap = st.empty()
        prog_gap = st.empty()

        if st.button("🔍 Scan & Fill Gaps"):
            if start_gap > end_gap:
                st.error("Start Date must be before End Date.")
            else:
                prog_gap.progress(0)
                def update_progress_gap(current, total, msg):
                    status_gap.text(f"{msg} ({current}/{total})")
                    if total > 0:
                        prog_gap.progress(min(1.0, current/total))

                results = asyncio.run(scraper_lib.run_batch_scrape(
                    str(start_gap), str(end_gap), entity_gap, kw_gap, update_progress_gap
                ))

                if results:
                    st.session_state.gap_results = pd.DataFrame(results)
                    st.success(f"Found {len(results)} articles. Please review and save below.")
                else:
                    st.warning("No new articles found.")

        if not st.session_state.gap_results.empty:
            st.divider()
            st.write(f"### 📥 Review Results ({len(st.session_state.gap_results)})")

            # Add Block Column
            if "Block" not in st.session_state.gap_results.columns:
                st.session_state.gap_results.insert(0, "Block", False)

            c_clear, c_block, c_save = st.columns([1, 1, 2])

            if c_clear.button("🗑️ Clear Results", key="gap_clear"):
                st.session_state.gap_results = pd.DataFrame()
                st.rerun()

            # Editor
            edited_gap_df = st.data_editor(st.session_state.gap_results, num_rows="dynamic", key="gap_editor")

            # Block Button
            if c_block.button("🚫 Block Selected", key="gap_block"):
                to_block = edited_gap_df[edited_gap_df["Block"] == True]
                if not to_block.empty:
                    with st.spinner(f"Blocking {len(to_block)} items..."):
                        for _, row in to_block.iterrows():
                             gsheet_handler.log_blocked_content(row.get("URL", ""), row.get("Judul", ""), "Manual Block")

                        remaining = edited_gap_df[edited_gap_df["Block"] == False].copy()
                        if "Block" in remaining.columns:
                            remaining = remaining.drop(columns=["Block"])

                        st.session_state.gap_results = remaining
                        st.success(f"Blocked {len(to_block)} items.")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.warning("No items selected to block.")

            # Save Button (Manual)
            if c_save.button("💾 Save Verified to Sheet", key="gap_save"):
                save_df = edited_gap_df[edited_gap_df["Block"] == False]
                if not save_df.empty:
                    with st.spinner("Saving to Google Sheets..."):
                        count = 0
                        last_sheet_name = "Unknown"
                        last_saved_title = ""

                        for index, row in save_df.iterrows():
                            if row.get("Judul"):
                                try:
                                    # Strict String Conversion
                                    row_dict = row.to_dict()
                                    if "Block" in row_dict: del row_dict["Block"]

                                    payload = {k: str(v).strip() if v is not None else "" for k, v in row_dict.items()}

                                    status_str = gsheet_handler.append_to_sheet(payload)

                                    # Parse real sheet name
                                    if " (" in status_str:
                                        last_sheet_name = status_str.rsplit(" (", 1)[0]
                                    else:
                                        last_sheet_name = status_str

                                    last_saved_title = payload.get("Judul")
                                    count += 1
                                except Exception as e:
                                    st.error(f"Error saving row {index}: {e}")

                        if count > 0:
                            st.success(f"Successfully saved {count} rows! Last location: '{last_sheet_name}'")

                            # Strict Verification
                            try:
                                time.sleep(1.5)
                                df_verify = gsheet_handler.read_sheet_to_df(worksheet_name=last_sheet_name)

                                if not df_verify.empty:
                                    recent_titles = df_verify.tail(10)["Judul"].astype(str).tolist()
                                    if last_saved_title in recent_titles:
                                        st.success(f"✅ Verified: '{last_saved_title}' found in sheet.")
                                    else:
                                        st.error(f"❌ Verification FAILED: '{last_saved_title}' NOT found in last 10 rows.")
                                        st.write(f"Sheet Headers Detected: {df_verify.columns.tolist()}")
                                        st.write("Recent rows found:", recent_titles)
                            except Exception as e:
                                st.error(f"Verification Check Failed: {e}")

                        time.sleep(2)
                        st.session_state.gap_results = pd.DataFrame()
                        st.rerun()
                else:
                    st.warning("No data to save.")

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
            if m_entity != "All": mask = mask & (df["Entitas"].astype(str).str.strip() == m_entity)
            st.dataframe(df[mask].sort_values(by="Tanggal", ascending=False))
        else:
            st.write("No data.")

    # --- 5. TROUBLESHOOT ---
    elif sub_page == "Troubleshoot Connection":
        st.subheader("🔧 Connection Troubleshooter")
        if st.button("Check Google Sheet Connection"):
            with st.spinner("Checking..."):
                info = gsheet_handler.check_connection()
                if isinstance(info, dict):
                    st.success(f"Connected to: **{info['title']}** (ID: `{info['id']}`)")
                    st.write("Available Worksheets:")
                    st.json(info['sheets'])
                else:
                    st.error(f"Connection Failed: {info}")

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
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    def update_progress(val, desc=""):
                        progress_bar.progress(val)
                        status_text.text(desc)

                    try:
                        _, msg = translator_utils.process_rows(to_proc, progress=update_progress)
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Translation failed: {e}")

    with tab2:
        if not df.empty and 'Judul_Inggris' in df.columns:
            st.dataframe(df[df['Judul_Inggris'] != ""])
