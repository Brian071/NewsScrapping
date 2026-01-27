from deep_translator import GoogleTranslator
import time
import random

_translator = None

def load_model():
    """
    Initializes the translator.
    For GoogleTranslator (API wrapper), no heavy model loading is needed.
    This function exists to maintain compatibility with existing frontend calls.
    """
    global _translator
    # We can instantiate a reusable object if needed, or just pass.
    # GoogleTranslator is lightweight.
    print("Translator initialized (Lightweight Mode).")
    return True

def smart_translate(text, target_lang='en'):
    """
    Translates text to the target language using Google Translate.
    Includes retry logic and basic error handling.
    """
    if not text or len(str(text)) < 2:
        return ""
        
    text = str(text)
    
    # Chunking logic for long text (Google Translate has limit ~5000 chars)
    # Simple split by newline or naive chunking
    if len(text) > 4500:
        parts = []
        current_chunk = ""
        for line in text.split('\n'):
            if len(current_chunk) + len(line) < 4500:
                current_chunk += line + "\n"
            else:
                parts.append(current_chunk)
                current_chunk = line + "\n"
        if current_chunk: parts.append(current_chunk)
    else:
        parts = [text]

    translated_parts = []
    
    for part in parts:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Add delay to avoid rate limits
                time.sleep(random.uniform(0.5, 1.5))

                res = GoogleTranslator(source='auto', target=target_lang).translate(part)
                if res:
                    translated_parts.append(res)
                break
            except Exception as e:
                print(f"Translation Error (Attempt {attempt+1}): {e}")
                time.sleep(2)
                if attempt == max_retries - 1:
                    # On failure, append original or partial?
                    # Let's append original to avoid data loss, or empty string.
                    # Appending original might be confusing. Let's return partial.
                    pass

    return "\n".join(translated_parts)
