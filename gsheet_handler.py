import gspread
import pandas as pd
from google.auth import default
import time

# Default Spreadsheet ID provided by user
DEFAULT_SPREADSHEET_ID = "1U8xeumDGJckZsTqIMyNr0DBfg0Bv9_IRpDV6XdN59Hw"

def get_creds():
    try:
        # Uses Colab's authenticated user credentials (ADC)
        creds, _ = default()
        return creds
    except Exception as e:
        print(f"Warning: Could not get default credentials. Ensure you are authenticated (e.g. in Colab). Error: {e}")
        return None

def get_worksheet(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name_or_index=0):
    """
    Retrieves a worksheet by index (int) or name (str).
    """
    creds = get_creds()
    if not creds:
        raise Exception("Authentication failed. Please authenticate with Google first.")
    
    gc = gspread.authorize(creds)
    try:
        sh = gc.open_by_key(sheet_id)
        
        # Check if worksheet exists, create if not (only if name provided)
        if isinstance(worksheet_name_or_index, str):
            try:
                return sh.worksheet(worksheet_name_or_index)
            except gspread.WorksheetNotFound:
                print(f"Worksheet '{worksheet_name_or_index}' not found. Creating it...")
                # Create with default headers for log if it's the log sheet
                ws = sh.add_worksheet(title=worksheet_name_or_index, rows=1000, cols=10)
                if worksheet_name_or_index == "log_kosong":
                    ws.append_row(["Tanggal", "Entitas", "Alasan", "Timestamp"])
                return ws
        else:
            return sh.get_worksheet(worksheet_name_or_index)
            
    except Exception as e:
        raise Exception(f"Could not open spreadsheet/worksheet: {e}")

def read_sheet_to_df(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name_or_index=0):
    try:
        ws = get_worksheet(sheet_id, worksheet_name_or_index)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Ensure standard columns exist for MAIN sheet only
        if worksheet_name_or_index == 0 or worksheet_name_or_index == "data_berita":
            required_columns = ["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris"]
            if df.empty:
                df = pd.DataFrame(columns=required_columns)
            else:
                for col in required_columns:
                    if col not in df.columns:
                        df[col] = ""
        
        # Ensure all data is string to avoid type issues
        df = df.astype(str)
        return df
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return pd.DataFrame()

def append_to_sheet(row_data, sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_name_or_index=0):
    """
    Appends a row to the sheet.
    row_data: dict with keys matching headers.
    """
    ws = get_worksheet(sheet_id, worksheet_name_or_index)
    headers = ws.row_values(1) # Get current headers
    
    if not headers:
        # If new sheet, init headers from keys
        headers = list(row_data.keys())
        ws.append_row(headers)
    
    row_values = []
    for h in headers:
        val = row_data.get(h, "")
        row_values.append(str(val))
        
    ws.append_row(row_values)
    return True

def find_row_index_by_keys(ws, date, entity, title):
    """
    Finds the physical row index (1-based) based on composite key.
    """
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
    """
    Updates a row identified by (date, entity, old_title).
    """
    ws = get_worksheet(sheet_id, 0) # Default to main sheet
    row_idx = find_row_index_by_keys(ws, date, entity, old_title)
    
    if not row_idx:
        raise Exception(f"Data not found for update: {old_title}")
    
    headers = ws.row_values(1)
    
    for key, value in new_data_dict.items():
        if key in headers:
            col_idx = headers.index(key) + 1
            ws.update_cell(row_idx, col_idx, str(value))
            
    return True

def delete_row_from_sheet(date, entity, title, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id, 0)
    row_idx = find_row_index_by_keys(ws, date, entity, title)
    
    if not row_idx:
        raise Exception(f"Data not found for deletion: {title}")
        
    ws.delete_rows(row_idx)
    return True

def bulk_append(df_batch, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id, 0)
    headers = ws.row_values(1)
    
    rows_to_append = []
    for _, row in df_batch.iterrows():
        row_vals = []
        for h in headers:
            val = row.get(h, "")
            row_vals.append(str(val))
        rows_to_append.append(row_vals)
        
    if rows_to_append:
        ws.append_rows(rows_to_append)

# --- Log Specific Functions ---

def log_empty_date(date, entity, reason="Manual Pass", sheet_id=DEFAULT_SPREADSHEET_ID):
    """
    Logs a date as empty/passed in the 'log_kosong' worksheet.
    """
    row_data = {
        "Tanggal": str(date),
        "Entitas": str(entity),
        "Alasan": str(reason),
        "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    return append_to_sheet(row_data, sheet_id, "log_kosong")

def get_empty_logs(sheet_id=DEFAULT_SPREADSHEET_ID):
    return read_sheet_to_df(sheet_id, "log_kosong")
