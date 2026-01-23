import streamlit as st
import pandas as pd
import gsheet_handler
from translator_utils import process_rows, revert_rows
import time

st.set_page_config(
    page_title="Auto AI Translator",
    page_icon="🤖",
    layout="wide"
)

# --- Helper Functions ---
def load_data():
    return gsheet_handler.read_sheet_to_df()

def get_pending_data(df):
    if df.empty: return df
    # Filter where translation is empty
    # Handle NaN or empty strings
    mask = (df['Judul_Inggris'].astype(str).str.strip() == "") | (df['Isi_Inggris'].astype(str).str.strip() == "") | (df['Judul_Inggris'].isnull())
    return df[mask].reset_index(drop=True)

def get_history_data(df):
    if df.empty: return df
    mask = (df['Judul_Inggris'].astype(str).str.strip() != "") & (df['Isi_Inggris'].astype(str).str.strip() != "")
    return df[mask].reset_index(drop=True)

# --- UI ---
st.title("🤖 Auto AI News Translator")

tab1, tab2 = st.tabs(["⏳ Pending Translations", "📜 Translation History"])

with tab1:
    st.header("Pending Translations")
    
    if st.button("🔄 Refresh Data", key="refresh_pending"):
        st.rerun()
        
    df = load_data()
    pending_df = get_pending_data(df)
    
    if not pending_df.empty:
        # Add a selection column manually since st.data_editor with key doesn't return selection easily for standard df
        # But we can use the "Select" column pattern
        if "Select" not in pending_df.columns:
            pending_df.insert(0, "Select", False)
            
        edited_df = st.data_editor(
            pending_df,
            column_config={
                "Select": st.column_config.CheckboxColumn("Translate?", default=False),
                "Isi": st.column_config.TextColumn("Isi (ID)", width="large"),
            },
            disabled=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris"],
            hide_index=True,
            key="editor_pending"
        )
        
        # Action Button
        if st.button("🚀 Translate Selected Rows"):
            selected_rows = edited_df[edited_df["Select"] == True]
            
            if selected_rows.empty:
                st.warning("Please select at least one row to translate.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # We need to wrap the callback to update streamlit UI
                def progress_callback(pct, desc):
                    progress_bar.progress(pct)
                    status_text.text(desc)
                
                try:
                    # process_rows expects the DataFrame directly
                    # It will use the composite keys (Tanggal, Entitas, Judul) to find and update
                    processed_df, msg = process_rows(selected_rows, batch_size=1, progress=progress_callback)
                    st.success(f"Translation Complete! {msg}")
                    time.sleep(2)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error during translation: {e}")
                    
    else:
        st.info("No pending translations found. Great job!")

with tab2:
    st.header("Translation History")
    
    if st.button("🔄 Refresh History", key="refresh_history"):
        st.rerun()
        
    df_hist = load_data()
    history_df = get_history_data(df_hist)
    
    if not history_df.empty:
        if "Select" not in history_df.columns:
            history_df.insert(0, "Select", False)
            
        edited_hist = st.data_editor(
            history_df,
            column_config={
                "Select": st.column_config.CheckboxColumn("Revert?", default=False),
                "Judul_Inggris": st.column_config.TextColumn("Title (EN)", width="medium"),
                "Isi_Inggris": st.column_config.TextColumn("Content (EN)", width="large"),
            },
            disabled=["Tanggal", "Entitas", "Judul", "Isi", "Judul_Inggris", "Isi_Inggris"],
            hide_index=True,
            key="editor_history"
        )
        
        if st.button("⚠️ Revert Selected (Delete Translation)"):
            to_revert = edited_hist[edited_hist["Select"] == True]
            
            if to_revert.empty:
                st.warning("Select rows to revert.")
            else:
                try:
                    _, msg = revert_rows(to_revert)
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error reverting: {e}")
    else:
        st.info("No translation history found.")
