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

def get_worksheet(sheet_id=DEFAULT_SPREADSHEET_ID, worksheet_index=0):
    creds = get_creds()
    if not creds:
        raise Exception("Authentication failed. Please authenticate with Google first (from google.colab import auth; auth.authenticate_user()).")
    
    gc = gspread.authorize(creds)
    try:
        sh = gc.open_by_key(sheet_id)
        return sh.get_worksheet(worksheet_index)
    except Exception as e:
        raise Exception(f"Could not open spreadsheet {sheet_id}: {e}")

def read_sheet_to_df(sheet_id=DEFAULT_SPREADSHEET_ID):
    try:
        ws = get_worksheet(sheet_id)
        # get_all_records returns a list of dictionaries
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Ensure standard columns exist
        required_columns = ["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris"]
        
        # If the sheet is empty (only headers or completely empty)
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
        # Return empty DF with columns to prevent crash
        return pd.DataFrame(columns=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris"])

def append_to_sheet(row_data, sheet_id=DEFAULT_SPREADSHEET_ID):
    """
    Appends a row to the sheet.
    row_data: dict with keys matching headers.
    """
    ws = get_worksheet(sheet_id)
    headers = ws.row_values(1) # Get current headers
    
    # If headers are missing, create them? 
    # For now assume headers exist.
    
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
    # Fetch all records to search
    # This might be slow for large datasets, but safer for consistency
    records = ws.get_all_records()
    
    search_title = str(title).strip().lower()
    search_date = str(date).strip()
    search_entity = str(entity).strip()
    
    for i, r in enumerate(records):
        # r keys match the headers
        r_date = str(r.get('Tanggal', '')).strip()
        r_entity = str(r.get('Entitas', '')).strip()
        r_title = str(r.get('Judul', '')).strip().lower()
        
        if r_date == search_date and r_entity == search_entity and r_title == search_title:
            return i + 2 # +2 because: +1 for 0-index list, +1 for header row
            
    return None

def update_row_in_sheet(date, entity, old_title, new_data_dict, sheet_id=DEFAULT_SPREADSHEET_ID):
    """
    Updates a row identified by (date, entity, old_title).
    new_data_dict contains the columns to update.
    """
    ws = get_worksheet(sheet_id)
    row_idx = find_row_index_by_keys(ws, date, entity, old_title)
    
    if not row_idx:
        raise Exception(f"Data not found for update: {old_title}")
    
    headers = ws.row_values(1)
    
    # Update specific cells
    # gspread update_cell is slow if done one by one.
    # Better to construct the full row or use range update if changing multiple.
    # But new_data_dict might be partial.
    
    for key, value in new_data_dict.items():
        if key in headers:
            col_idx = headers.index(key) + 1
            ws.update_cell(row_idx, col_idx, str(value))
            
    return True

def delete_row_from_sheet(date, entity, title, sheet_id=DEFAULT_SPREADSHEET_ID):
    ws = get_worksheet(sheet_id)
    row_idx = find_row_index_by_keys(ws, date, entity, title)
    
    if not row_idx:
        raise Exception(f"Data not found for deletion: {title}")
        
    ws.delete_rows(row_idx)
    return True

def bulk_append(df_batch, sheet_id=DEFAULT_SPREADSHEET_ID):
    """
    Appends multiple rows from a DataFrame.
    """
    ws = get_worksheet(sheet_id)
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
        
