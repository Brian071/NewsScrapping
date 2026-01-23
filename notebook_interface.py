import ipywidgets as widgets
from IPython.display import display, clear_output
import pandas as pd
from datetime import datetime
import asyncio
import nest_asyncio

# Local Services
import scraper_service
import gsheet_handler
import translator_utils

# Patch loop for notebook environment
nest_asyncio.apply()

# --- Global State ---
class AppState:
    def __init__(self):
        self.scraped_data = pd.DataFrame()

state = AppState()

# --- UI Components ---
def create_ui():
    """Creates and displays the main Jupyter Widget UI."""

    # Header
    title = widgets.HTML("<h2>🤖 Auto AI News System (Notebook Edition)</h2>")

    # Tabs
    tab = widgets.Tab()

    # --- TAB 1: SCRAPING ---

    # Inputs
    start_date = widgets.DatePicker(description='Start Date', value=datetime.now().date())
    end_date = widgets.DatePicker(description='End Date', value=datetime.now().date())
    entity = widgets.Dropdown(
        options=['AirAsia', 'Garuda Indonesia'],
        value='AirAsia',
        description='Entity:',
    )
    keywords = widgets.Text(description='Keywords:', placeholder='e.g. saham, promo')

    btn_scrape = widgets.Button(
        description='🚀 Start Scraping',
        button_style='primary', # 'success', 'info', 'warning', 'danger' or ''
        icon='search'
    )

    out_scrape = widgets.Output()

    # Scrape Result Area
    lbl_result = widgets.Label("Results:")
    out_table = widgets.Output()

    btn_save = widgets.Button(
        description='💾 Save to Sheet',
        button_style='success',
        icon='save',
        disabled=True
    )

    # Event Handlers
    def on_click_scrape(b):
        with out_scrape:
            clear_output()
            print("⏳ Scraping started... Please wait.")

            try:
                # Run Async Scraper
                s_date = str(start_date.value)
                e_date = str(end_date.value)
                kw = keywords.value
                ent = entity.value

                # In Notebook, we can just await directly if in an async cell,
                # but standard button callbacks are sync.
                # We use the event loop already running in Jupyter.
                loop = asyncio.get_event_loop()
                data = loop.run_until_complete(scraper_service.scrape_batch(s_date, e_date, ent, kw))

                state.scraped_data = pd.DataFrame(data)

                if not state.scraped_data.empty:
                    print(f"✅ Found {len(data)} articles!")
                    btn_save.disabled = False
                    with out_table:
                        clear_output()
                        display(state.scraped_data)
                else:
                    print("⚠️ No articles found.")
                    btn_save.disabled = True

            except Exception as e:
                print(f"❌ Error: {e}")

    def on_click_save(b):
        with out_scrape:
            if state.scraped_data.empty:
                print("Nothing to save.")
                return

            print("⏳ Saving to Google Sheet...")
            count = 0
            for _, row in state.scraped_data.iterrows():
                # Only save if 'Pilih' is arguably True (logic simplified here as widgets don't easily support row selection without more complex grids like ipydatagrid)
                # We assume all found are saved for now, or we could add a selection logic later.
                clean_data = {
                    "Tanggal": row.get("Tanggal"),
                    "Entitas": row.get("Entitas"),
                    "Judul": row.get("Judul"),
                    "Isi": row.get("Isi"),
                    "URL": row.get("URL", ""),
                    "Judul_Inggris": "",
                    "Isi_Inggris": ""
                }
                try:
                    gsheet_handler.append_to_sheet(clean_data)
                    count += 1
                except Exception as e:
                    print(f"Failed to save {row.get('Judul')}: {e}")

            print(f"✅ Saved {count} rows successfully!")

    btn_scrape.on_click(on_click_scrape)
    btn_save.on_click(on_click_save)

    # Layout Tab 1
    box_scrape = widgets.VBox([
        widgets.HBox([start_date, end_date]),
        widgets.HBox([entity, keywords]),
        btn_scrape,
        out_scrape,
        lbl_result,
        out_table,
        btn_save
    ])

    # --- TAB 2: TRANSLATOR ---

    btn_load_pending = widgets.Button(description='🔄 Load Pending', button_style='info')
    btn_translate = widgets.Button(description='🅰️ Translate All Pending', button_style='warning', disabled=True)
    out_trans = widgets.Output()

    def on_click_load(b):
        with out_trans:
            clear_output()
            print("⏳ Loading data from Sheet...")
            df = gsheet_handler.read_sheet_to_df()
            if df.empty:
                print("Sheet is empty or failed to load.")
                return

            # Filter Pending
            if 'Judul_Inggris' in df.columns:
                mask = (df['Judul_Inggris'] == "") | (df['Isi_Inggris'] == "")
                pending = df[mask]

                if not pending.empty:
                    print(f"Found {len(pending)} pending translations.")
                    display(pending.head())
                    state.pending_data = pending
                    btn_translate.disabled = False
                else:
                    print("✅ No pending translations found.")
                    btn_translate.disabled = True
            else:
                print("Column 'Judul_Inggris' not found.")

    def on_click_translate(b):
        with out_trans:
            if not hasattr(state, 'pending_data') or state.pending_data.empty:
                print("No data to translate.")
                return

            print("⏳ Starting Translation (this may take a while)...")

            # Define a simple progress callback printer
            def progress_print(pct, desc):
                # Simple progress indication
                if pct * 100 % 10 == 0:
                    print(f"Status: {desc}")

            try:
                processed, msg = translator_utils.process_rows(state.pending_data, progress=progress_print)
                print(f"✅ {msg}")
                # Reload
                on_click_load(None)
            except Exception as e:
                print(f"❌ Error: {e}")

    btn_load_pending.on_click(on_click_load)
    btn_translate.on_click(on_click_translate)

    box_trans = widgets.VBox([
        btn_load_pending,
        out_trans,
        btn_translate
    ])

    # --- TAB 3: MONITOR ---

    btn_refresh = widgets.Button(description='Refresh Data', icon='refresh')
    out_monitor = widgets.Output()

    def on_click_refresh(b):
        with out_monitor:
            clear_output()
            df = gsheet_handler.read_sheet_to_df()
            display(df)

    btn_refresh.on_click(on_click_refresh)

    box_monitor = widgets.VBox([btn_refresh, out_monitor])

    # Final Assembly
    tab.children = [box_scrape, box_trans, box_monitor]
    tab.set_title(0, '📝 Scraping')
    tab.set_title(1, '🔄 Translator')
    tab.set_title(2, '📊 Monitor')

    display(title, tab)
