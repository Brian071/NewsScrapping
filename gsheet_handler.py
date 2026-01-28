import gspread
import pandas as pd
from google.auth import default
import time
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

def read_sheet_to_df(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
    try:
        target_name = worksheet_name if isinstance(worksheet_name, str) else "data_berita"
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
        return pd.DataFrame()

def append_to_sheet(row_data, sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
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
        # value_input_option='USER_ENTERED' prevents automatic formatting (like dates)
        resp = ws.append_row(row_values, value_input_option='USER_ENTERED')

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
        if "Quota exceeded" in str(e):
            print("Quota exceeded, retrying...")
            time.sleep(2)
            ws.append_row(row_values, value_input_option='USER_ENTERED')
            return f"{ws.title} (Retry)"
        raise e

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
    
    for key, value in new_data_dict.items():
        if key in headers:
            col_idx = headers.index(key) + 1
            try:
                ws.update_cell(row_idx, col_idx, str(value))
            except Exception as e:
                if "Quota exceeded" in str(e):
                    time.sleep(2)
                    ws.update_cell(row_idx, col_idx, str(value))
                else:
                    raise e
    return True

def delete_row_from_sheet(date, entity, title, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id, "data_berita")
    row_idx = find_row_index_by_keys(ws, date, entity, title)
    
    if not row_idx:
        raise Exception(f"Data not found for deletion: {title}")
    ws.delete_rows(row_idx)
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
        try:
            ws.append_rows(rows_to_append)
        except Exception as e:
            if "Quota exceeded" in str(e):
                time.sleep(5)
                ws.append_rows(rows_to_append)
            else:
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
