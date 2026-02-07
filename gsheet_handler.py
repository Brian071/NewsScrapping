import gspread
import pandas as pd
from google.auth import default
import time
import random
from gspread.utils import rowcol_to_a1
import re

# Default Spreadsheet ID provided by user
DEFAULT_SPREADSHEET_ID = "1U8xeumDGJckZsTqIMyNr0DBfg0Bv9_IRpDV6XdN59Hw"

# Import Config to override if needed
try:
    import config
    if hasattr(config, 'SPREADSHEET_ID'):
        DEFAULT_SPREADSHEET_ID = config.SPREADSHEET_ID
except ImportError:
    pass

def get_creds():
    try:
        creds, _ = default()
        return creds
    except Exception as e:
        print(f"Warning: Could not get default credentials. Error: {e}")
        return None

def retry_with_backoff(func, max_retries=5, initial_delay=2, backoff_factor=2):
    """
    Retry logic for API calls with exponential backoff and jitter.
    """
    def wrapper(*args, **kwargs):
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Check for API Quota errors (429) or other temporary issues
                error_msg = str(e)
                is_quota = "429" in error_msg or "Quota exceeded" in error_msg
                is_server_error = "500" in error_msg or "503" in error_msg

                if (is_quota or is_server_error) and attempt < max_retries - 1:
                    sleep_time = delay + random.uniform(0, 1) # Add jitter
                    print(f"DEBUG: API Error ({error_msg}). Retrying in {sleep_time:.2f}s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(sleep_time)
                    delay *= backoff_factor
                else:
                    print(f"ERROR: API Request failed after {attempt+1} attempts: {e}")
                    raise e
    return wrapper

@retry_with_backoff
def get_worksheet(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
    """
    Safely retrieve or create a worksheet by name.
    If worksheet_name is 'data_berita' but does not exist, it tries to use the first sheet (index 0).
    """
    creds = get_creds()
    if not creds:
        raise Exception("Authentication failed. Please authenticate with Google first.")
    
    gc = gspread.authorize(creds)
    try:
        sh = gc.open_by_key(sheet_id)
        
        # Try to access by name
        try:
            return sh.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            # Fallback: If expecting main data but not found, try the first visible sheet
            if worksheet_name == "data_berita":
                print(f"Worksheet '{worksheet_name}' not found. Falling back to the first sheet (gid=0).")
                try:
                    ws = sh.get_worksheet(0)
                    headers = ws.row_values(1)
                    if not headers:
                         ws.append_row(["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])
                    return ws
                except Exception as ex:
                    print(f"Fallback to first sheet failed: {ex}")

            print(f"Worksheet '{worksheet_name}' not found. Creating it...")
            
            # Create new sheet
            ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=10)
            
            # Initialize Headers based on type
            if worksheet_name == "log_kosong":
                ws.append_row(["Tanggal", "Entitas", "Alasan", "Timestamp"])
            elif worksheet_name == "blocked_content":
                ws.append_row(["URL", "Title", "Reason", "Timestamp"])
            else:
                ws.append_row(["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])
            return ws
            
    except Exception as e:
        raise Exception(f"Could not open spreadsheet/worksheet: {e}")

def check_connection(sheet_id=DEFAULT_SPREADSHEET_ID):
    """Debug tool to verify connection and available sheets"""
    creds = get_creds()
    if not creds:
        return "Authentication Failed"

    gc = gspread.authorize(creds)
    try:
        sh = gc.open_by_key(sheet_id)
        info = {
            "title": sh.title,
            "id": sh.id,
            "sheets": []
        }
        for ws in sh.worksheets():
            info["sheets"].append({
                "title": ws.title,
                "id": ws.id,
                "rows": ws.row_count,
                "cols": ws.col_count
            })
        return info
    except Exception as e:
        return str(e)

@retry_with_backoff
def read_sheet_to_df(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
    try:
        target_name = worksheet_name if isinstance(worksheet_name, str) else "data_berita"
        # Since get_worksheet is also retried, we should probably handle recursion or just rely on it.
        # But wait, get_worksheet is decorated, so calling it here will invoke the wrapper.
        ws = get_worksheet(sheet_id, target_name)
        data = ws.get_all_records()
        
        print(f"DEBUG: read_sheet_to_df found {len(data)} records in {target_name} (Sheet ID: {ws.id})")
        
        df = pd.DataFrame(data)
        
        # Normalize DataFrame Columns: Strip whitespace
        if not df.empty:
            df.columns = [str(c).strip() for c in df.columns]

        if target_name == "data_berita":
            required_columns = ["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"]
            
            if df.empty:
                df = pd.DataFrame(columns=required_columns)
            else:
                for col in required_columns:
                    if col not in df.columns:
                        df[col] = ""
        
        df = df.astype(str)
        return df
    except Exception as e:
        print(f"Error reading sheet '{worksheet_name}': {e}")
        # Retrying read_sheet_to_df is handled by the decorator on this function.
        if "Quota exceeded" in str(e) or "429" in str(e):
             raise e
        return pd.DataFrame()

def append_to_sheet(row_data, sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
    # 0. Check for Duplicates (Double Save Prevention)
    # Only perform this check for main data or blocked content, not logs if not critical
    if worksheet_name in ["data_berita", "blocked_content"]:
        try:
            # We need to efficiently check if the record exists.
            # Ideally, we should have a cached copy, but here we might need to read the sheet.
            # To avoid excessive reads, we can use the 'read_sheet_to_df' which is cached/retried?
            # No, reading the whole sheet for every save is expensive.
            # A better approach for this specific user issue (clicking save twice rapidly) might be handled in frontend state.
            # BUT, the requirement is "system otomatis memblokir duplikat save".

            # Let's try to verify against the existing sheet data.
            # Optimization: Only check if we have a URL or Title.
            target_url = str(row_data.get("URL", "")).strip()
            target_title = str(row_data.get("Judul", row_data.get("Title", ""))).strip().lower()

            if target_url or target_title:
                # We can use find_row_index_by_keys but optimize it to not fetch all records every time if possible?
                # Currently find_row_index_by_keys calls get_all_records().
                # This is heavy for a loop save.
                # However, for safety against duplicate saves, we must check.

                # Use a specific check function that might be lighter or just accept the cost for safety.
                # Or relying on the retry logic to handle the load.

                # Check for existing record
                ws = get_worksheet(sheet_id, worksheet_name)
                records = ws.get_all_records() # This is the heavy part.

                for r in records:
                    r_url = str(r.get("URL", "")).strip()
                    r_title = str(r.get("Judul", r.get("Title", ""))).strip().lower()

                    # Match by URL if present, or Title as fallback
                    if target_url and r_url == target_url:
                        print(f"Duplicate detected by URL: {target_url}")
                        return f"{ws.title} (Skipped: Duplicate)"
                    if target_title and r_title == target_title:
                         # Double check date/entity if possible to avoid false positives on generic titles?
                         # For now, strict title match is likely what is intended to prevent double clicks.
                         print(f"Duplicate detected by Title: {target_title}")
                         return f"{ws.title} (Skipped: Duplicate)"

        except Exception as e:
            print(f"Warning: Duplicate check failed, proceeding to append. Error: {e}")

    # 1. Content Chunking (Handle >45k chars)
    for col_check in ["Isi", "Isi_Inggris"]:
        content = str(row_data.get(col_check, ""))
        if len(content) > 45000:
            print(f"DEBUG: Content in '{col_check}' exceeds 45k chars ({len(content)}). Splitting...")

            chunk_size = 45000
            parts = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

            base_title = row_data.get("Judul", "")
            base_url = row_data.get("URL", "")
            last_status = ""

            for i, part in enumerate(parts):
                new_row = row_data.copy()
                new_row[col_check] = part

                if i > 0:
                    new_row["Judul"] = f"{base_title} (Part {i+1})"
                    new_row["URL"] = f"{base_url}#part{i+1}"

                # Recursive call with the modified row (which now has <45k chars in this column)
                # IMPORTANT: Pass the original 'worksheet_name', NOT the return value (which is a status string)
                last_status = append_to_sheet(new_row, sheet_id, worksheet_name)
                time.sleep(1)

            # Return the status of the *last* chunk saved (usually sufficient)
            return last_status

    # Internal function to perform the actual append with retry logic
    @retry_with_backoff
    def _perform_append(ws, values):
        return ws.append_row(values, value_input_option='USER_ENTERED')

    ws = get_worksheet(sheet_id, worksheet_name)
    headers = ws.row_values(1)
    
    if not headers:
        headers = list(row_data.keys())
        ws.append_row(headers)
    
    # 2. Fuzzy Header Matching
    data_map = {k.strip().lower(): v for k, v in row_data.items()}
    row_values = []

    # Debug info
    print(f"DEBUG: Sheet Headers: {headers}")

    for h in headers:
        h_norm = str(h).strip().lower()
        val = data_map.get(h_norm, "")
        row_values.append(str(val))
        
    try:
        # 3. Capture Detailed Response
        # Using the internal retry wrapper
        resp = _perform_append(ws, row_values)

        # Parse range from response (e.g. {'spreadsheetId': '...', 'updates': {'spreadsheetId': '...', 'updatedRange': 'Sheet1!A10:G10', ...}})
        updated_range = "Unknown"
        if resp and isinstance(resp, dict):
             updates = resp.get('updates', {})
             updated_range = updates.get('updatedRange', 'Unknown Range')

        # Try to extract row number from range (e.g. 'Sheet1!A10:G10' -> 10)
        row_num = "?"
        if updated_range != "Unknown":
            match = re.search(r'!A(\d+):', updated_range)
            if match:
                row_num = match.group(1)
            else:
                 # Fallback regex for generic range
                 match = re.search(r'\d+$', updated_range)
                 if match: row_num = match.group(0)

        # Return string with debugging info
        return f"{ws.title} (Row {row_num})"

    except Exception as e:
        print(f"ERROR: Append failed: {e}")
        # Retry is handled by _perform_append, but if it fails after retries, we might want to catch it here.
        raise e

@retry_with_backoff
def find_row_index_by_keys(ws, date, entity, title):
    records = ws.get_all_records()
    search_title = str(title).strip().lower()
    search_date = str(date).strip()
    search_entity = str(entity).strip()
    
    for i, r in enumerate(records):
        r_date = str(r.get('Tanggal', '')).strip()
        r_entity = str(r.get('Entitas', '')).strip()
        r_title = str(r.get('Judul', '')).strip().lower()
        
        if r_date == search_date and r_entity == search_entity and r_title == search_title:
            return i + 2 
            
    return None

def update_row_in_sheet(date, entity, old_title, new_data_dict, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id, "data_berita")
    row_idx = find_row_index_by_keys(ws, date, entity, old_title)
    
    if not row_idx:
        raise Exception(f"Data not found for update: {old_title}")
    
    headers = ws.row_values(1)
    
    @retry_with_backoff
    def _perform_update(ws, r_idx, c_idx, val):
        ws.update_cell(r_idx, c_idx, val)

    for key, value in new_data_dict.items():
        if key in headers:
            col_idx = headers.index(key) + 1
            try:
                _perform_update(ws, row_idx, col_idx, str(value))
            except Exception as e:
                print(f"Failed to update cell: {e}")
                # Optional: Continue or raise? Raising is safer.
                raise e
    return True

def delete_row_from_sheet(date, entity, title, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id, "data_berita")
    row_idx = find_row_index_by_keys(ws, date, entity, title)
    
    if not row_idx:
        raise Exception(f"Data not found for deletion: {title}")

    @retry_with_backoff
    def _perform_delete(ws, idx):
        ws.delete_rows(idx)

    _perform_delete(ws, row_idx)
    return True

def bulk_append(df_batch, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id, "data_berita")
    headers = ws.row_values(1)
    
    if not headers and not df_batch.empty:
        headers = df_batch.columns.tolist()
        ws.append_row(headers)
    
    # Normalize headers map
    header_indices = {str(h).strip().lower(): i for i, h in enumerate(headers)}

    rows_to_append = []
    for _, row in df_batch.iterrows():
        # Create a blank row of empty strings
        row_vals = [""] * len(headers)

        # Fill in values based on fuzzy matching
        for k, v in row.items():
            k_norm = str(k).strip().lower()
            if k_norm in header_indices:
                idx = header_indices[k_norm]
                row_vals[idx] = str(v)

        rows_to_append.append(row_vals)
        
    if rows_to_append:
        @retry_with_backoff
        def _perform_bulk_append(ws, rows):
            ws.append_rows(rows)

        try:
            _perform_bulk_append(ws, rows_to_append)
        except Exception as e:
            raise e

# --- Log Specific Functions ---

def log_empty_date(date, entity, reason="Manual Pass", sheet_id=DEFAULT_SPREADSHEET_ID):
    df = read_sheet_to_df(sheet_id, "log_kosong")
    if not df.empty:
        exists = df[(df['Tanggal'] == str(date)) & (df['Entitas'] == str(entity))]
        if not exists.empty:
            print(f"Log for {date} {entity} already exists. Skipping duplicate log.")
            return True

    row_data = {
        "Tanggal": str(date),
        "Entitas": str(entity),
        "Alasan": str(reason),
        "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    return append_to_sheet(row_data, sheet_id, "log_kosong")

def get_empty_logs(sheet_id=DEFAULT_SPREADSHEET_ID):
    return read_sheet_to_df(sheet_id, "log_kosong")

# --- Blocked Content Functions ---

def log_blocked_content(url, title, reason="Spam", sheet_id=DEFAULT_SPREADSHEET_ID):
    """Logs blocked content to 'blocked_content' sheet"""
    row_data = {
        "URL": str(url),
        "Title": str(title),
        "Reason": str(reason),
        "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    # Append to blocked_content, creating it if needed
    return append_to_sheet(row_data, sheet_id, "blocked_content")

def get_blocked_content(sheet_id=DEFAULT_SPREADSHEET_ID):
    """Reads blocked content into a DataFrame"""
    return read_sheet_to_df(sheet_id, "blocked_content")

# --- Archive Functions ---

def archive_data(row_data, sheet_id=DEFAULT_SPREADSHEET_ID):
    """
    Moves a row from 'data_berita' to 'archive_berita'.
    1. Appends to 'archive_berita'.
    2. Deletes from 'data_berita'.
    """
    try:
        # 1. Append to Archive
        # We pass "archive_berita" as the target.
        print(f"Archiving: {row_data.get('Judul', 'Unknown')}")
        status = append_to_sheet(row_data, sheet_id, worksheet_name="archive_berita")

        # 2. Delete from Main Sheet
        # Identify by keys
        date = row_data.get('Tanggal')
        entity = row_data.get('Entitas')
        title = row_data.get('Judul')

        if date and entity and title:
            delete_row_from_sheet(date, entity, title, sheet_id)
            return f"Archived to {status} and deleted from source."
        else:
            return f"Copied to {status}, but skipped delete (missing keys)."

    except Exception as e:
        raise Exception(f"Archive failed: {e}")
