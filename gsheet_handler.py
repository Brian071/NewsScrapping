import gspread
import pandas as pd
from google.auth import default
import time
from gspread.utils import rowcol_to_a1

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
            print(f"Worksheet '{worksheet_name}' not found. Creating it...")
            
            # Create new sheet
            ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=10)
            
            # Initialize Headers based on type
            if worksheet_name == "log_kosong":
                ws.append_row(["Tanggal", "Entitas", "Alasan", "Timestamp"])
            else:
                # Default for data_berita
                # Added URL for verification and duplicate checking
                ws.append_row(["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"])
            return ws
            
    except Exception as e:
        raise Exception(f"Could not open spreadsheet/worksheet: {e}")

def read_sheet_to_df(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
    try:
        # Default to index 0 if not specified name, but prefer name
        target_name = worksheet_name if isinstance(worksheet_name, str) else "data_berita"
        
        ws = get_worksheet(sheet_id, target_name)
        data = ws.get_all_records()
        
        print(f"DEBUG: read_sheet_to_df found {len(data)} records in {target_name}")
        
        df = pd.DataFrame(data)
        
        # Ensure standard columns exist for MAIN sheet only
        if target_name == "data_berita":
            required_columns = ["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris", "URL"]
            
            # If empty or missing columns
            if df.empty:
                df = pd.DataFrame(columns=required_columns)
            else:
                for col in required_columns:
                    if col not in df.columns:
                        df[col] = ""
        
        # Ensure all data is string
        df = df.astype(str)
        return df
    except Exception as e:
        print(f"Error reading sheet '{worksheet_name}': {e}")
        return pd.DataFrame()

def append_to_sheet(row_data, sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name="data_berita"):
    ws = get_worksheet(sheet_id, worksheet_name)
    headers = ws.row_values(1)
    
    if not headers:
        headers = list(row_data.keys())
        ws.append_row(headers)
    
    row_values = []
    for h in headers:
        val = row_data.get(h, "")
        row_values.append(str(val))
        
    try:
        # Force USER_ENTERED to ensure strings are treated as such
        print(f"DEBUG: Appending row to {worksheet_name}: {row_values[:2]}...")
        ws.append_row(row_values, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        print(f"ERROR: Append failed: {e}")
        if "Quota exceeded" in str(e):
            print("Quota exceeded, retrying...")
            time.sleep(2)
            ws.append_row(row_values, value_input_option='USER_ENTERED')
            return True
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
        # Initialize headers if completely empty
        headers = df_batch.columns.tolist()
        ws.append_row(headers)
    
    rows_to_append = []
    for _, row in df_batch.iterrows():
        row_vals = []
        for h in headers:
            val = row.get(h, "")
            row_vals.append(str(val))
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
    # Check for duplicates first
    df = read_sheet_to_df(sheet_id, "log_kosong")
    if not df.empty:
        # Check if Date + Entity already exists
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
