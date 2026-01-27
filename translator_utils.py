import os
import pandas as pd
from transformers import pipeline
import torch
from llama_index.core.node_parser import SentenceSplitter
import gsheet_handler

# Global model cache
_translator = None
_splitter = None

def load_resources():
    """
    Loads the NLLB-200 translation pipeline and LlamaIndex splitter.
    """
    global _translator, _splitter
    if _translator is None:
        print("Loading NLLB-200 model...")
        device = 0 if torch.cuda.is_available() else -1
        # Use lighter model for Colab stability: facebook/nllb-200-distilled-600M
        _translator = pipeline("translation", model="facebook/nllb-200-distilled-600M", src_lang="ind_Latn", tgt_lang="eng_Latn", device=device)

    if _splitter is None:
        print("Loading LlamaIndex SentenceSplitter...")
        # Reduce chunk_size to 64 to ensure NLLB doesn't truncate output.
        # NLLB seems to struggle with long context > 200 tokens output generation.
        # 64 tokens is safer to ensure complete translation of every sentence.
        _splitter = SentenceSplitter(chunk_size=64, chunk_overlap=0)

    return _translator, _splitter

def smart_translate(text, translator, splitter):
    """
    Translates text using LlamaIndex SentenceSplitter and NLLB-200.
    """
    if not text or not isinstance(text, str) or text.strip() == "":
        return ""
        
    # 1. Chunking via LlamaIndex
    chunks = splitter.split_text(text)
    
    # 2. Translation
    translated_parts = []
    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            # max_length=512 is plenty for a 128 token input
            res = translator(chunk, max_length=512, truncation=True)
            translated_parts.append(res[0]['translation_text'])
        except Exception as e:
            print(f"Chunk translation error: {e}")
            translated_parts.append(chunk)

    return " ".join(translated_parts)

def process_rows(selected_df, batch_size=1, progress=None):
    """
    Translates the specified rows in selected_df and updates the Google Sheet.
    Uses Composite Key (Tanggal, Entitas, Judul) to find rows.
    """
    if selected_df.empty:
        return pd.DataFrame(), "No rows selected."

    translator, splitter = load_resources()
    
    total = len(selected_df)
    processed_count = 0
    errors = 0

    print(f"Processing {total} selected rows...")

    # We will return the updated dataframe so the UI can reflect changes
    # Make a copy to avoid SettingWithCopy warnings
    result_df = selected_df.copy()

    for index, row in result_df.iterrows():
        # Keys for finding the row
        r_date = row.get('Tanggal')
        r_entity = row.get('Entitas')
        r_judul = row.get('Judul')

        # Current Values
        judul_ing = row.get('Judul_Inggris', '')
        isi_ing = row.get('Isi_Inggris', '')
        r_isi = row.get('Isi', '')

        updated_fields = {}

        # Translate Judul
        if not judul_ing or str(judul_ing).strip() == "":
             trans_judul = smart_translate(r_judul, translator, splitter)
             updated_fields['Judul_Inggris'] = trans_judul
             result_df.at[index, 'Judul_Inggris'] = trans_judul

        # Translate Isi
        if not isi_ing or str(isi_ing).strip() == "":
             trans_isi = smart_translate(r_isi, translator, splitter)
             updated_fields['Isi_Inggris'] = trans_isi
             result_df.at[index, 'Isi_Inggris'] = trans_isi

        # Update Sheet immediately if there are changes
        if updated_fields:
            try:
                success = gsheet_handler.update_row_in_sheet(
                    date=r_date,
                    entity=r_entity,
                    old_title=r_judul,
                    new_data_dict=updated_fields
                )
                if not success:
                    print(f"Failed to find row in Sheet: {r_judul}")
                    errors += 1
            except Exception as e:
                print(f"Error updating row {r_judul}: {e}")
                errors += 1

        processed_count += 1
        if progress:
            progress(processed_count / total, desc=f"Processed {processed_count}/{total}")

    return result_df, f"Processed {processed_count} rows. Errors/Not Found: {errors}"

def revert_rows(selected_df, progress=None):
    """
    Reverts translations for the specified rows in selected_df.
    """
    if selected_df.empty:
        return pd.DataFrame(), "No rows selected."

    print(f"Reverting {len(selected_df)} rows...")

    result_df = selected_df.copy()
    errors = 0

    for index, row in result_df.iterrows():
        r_date = row.get('Tanggal')
        r_entity = row.get('Entitas')
        r_judul = row.get('Judul')

        fields = {'Judul_Inggris': '', 'Isi_Inggris': ''}

        try:
             success = gsheet_handler.update_row_in_sheet(
                date=r_date,
                entity=r_entity,
                old_title=r_judul,
                new_data_dict=fields
            )
             if success:
                 result_df.at[index, 'Judul_Inggris'] = ''
                 result_df.at[index, 'Isi_Inggris'] = ''
             else:
                 errors += 1
        except Exception as e:
            print(f"Failed to revert row {r_judul}: {e}")
            errors += 1

    return result_df, f"Reverted {len(selected_df)} rows. Errors: {errors}"
