import os
import pandas as pd
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import torch
from llama_index.core.node_parser import SentenceSplitter
import gsheet_handler
from langdetect import detect, LangDetectException

# Global model cache
_tokenizer = None
_model = None
_splitter = None

def load_resources():
    """
    Loads the NLLB-200 tokenizer and model directly.
    """
    global _tokenizer, _model, _splitter

    model_name = "facebook/nllb-200-1.3B"

    if _tokenizer is None:
        print(f"Loading Tokenizer for {model_name}...")
        _tokenizer = AutoTokenizer.from_pretrained(model_name)

    if _model is None:
        print(f"Loading Model for {model_name}...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(device)

    if _splitter is None:
        print("Loading LlamaIndex SentenceSplitter...")
        # Reduce chunk_size to 64 to ensure NLLB doesn't truncate output.
        _splitter = SentenceSplitter(chunk_size=64, chunk_overlap=0)

    return _tokenizer, _model, _splitter

def smart_translate(text, tokenizer, model, splitter):
    """
    Translates text using LlamaIndex SentenceSplitter and NLLB-200 model directly.
    Skips translation if text is detected as English.
    """
    if not text or not isinstance(text, str) or text.strip() == "":
        return ""

    # 0. Language Detection
    try:
        lang = detect(text)
        if lang == 'en':
            return text
    except LangDetectException:
        pass # Fallback to translate if detection fails
        
    # 1. Chunking via LlamaIndex
    chunks = splitter.split_text(text)
    
    # 2. Translation
    translated_parts = []
    device = model.device

    # Set source language to Indonesian (ind_Latn)
    tokenizer.src_lang = "ind_Latn"

    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            # Tokenize
            inputs = tokenizer(chunk, return_tensors="pt", padding=True, truncation=True, max_length=128).to(device)

            # Generate Translation (Target: eng_Latn)
            # forced_bos_token_id is crucial for NLLB target language
            translated_tokens = model.generate(
                **inputs,
                forced_bos_token_id=tokenizer.lang_code_to_id["eng_Latn"],
                max_length=512
            )

            # Decode
            trans_text = tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]
            translated_parts.append(trans_text)

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

    tokenizer, model, splitter = load_resources()
    
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
             trans_judul = smart_translate(r_judul, tokenizer, model, splitter)
             updated_fields['Judul_Inggris'] = trans_judul
             result_df.at[index, 'Judul_Inggris'] = trans_judul

        # Translate Isi
        if not isi_ing or str(isi_ing).strip() == "":
             trans_isi = smart_translate(r_isi, tokenizer, model, splitter)
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
