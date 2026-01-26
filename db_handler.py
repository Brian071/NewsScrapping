import sqlite3
import json
import time
import os
from datetime import datetime

# Configuration
COLAB_DRIVE_PATH = "/content/drive/MyDrive/AutoNews_DB"
LOCAL_DB_NAME = "app.db"

# Global cache for DB path to avoid repeated print statements
_cached_db_path = None

def get_db_path():
    """
    Determines the best location for the SQLite database.
    1. Checks if Google Drive is mounted at /content/drive/MyDrive
    2. If yes, creates/uses a folder 'AutoNews_DB' and stores app.db there.
    3. If no, uses local 'app.db'.
    """
    global _cached_db_path
    if _cached_db_path:
        return _cached_db_path

    if os.path.exists("/content/drive/MyDrive"):
        # We are likely in Colab with Drive mounted
        if not os.path.exists(COLAB_DRIVE_PATH):
            try:
                os.makedirs(COLAB_DRIVE_PATH, exist_ok=True)
                print(f"Created Database Folder in Drive: {COLAB_DRIVE_PATH}")
            except Exception as e:
                print(f"Warning: Could not create folder in Drive ({e}). Using local DB.")
                _cached_db_path = LOCAL_DB_NAME
                return LOCAL_DB_NAME

        db_path = os.path.join(COLAB_DRIVE_PATH, "app.db")
        print(f"Using Google Drive Database: {db_path}")
        _cached_db_path = db_path
        return db_path
    else:
        # Local environment
        print(f"Using Local Database: {LOCAL_DB_NAME}")
        _cached_db_path = LOCAL_DB_NAME
        return LOCAL_DB_NAME

def get_conn():
    db_path = get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"DB Connect Error ({db_path}): {e}")
        raise e

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Table: Jobs
    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT,
            total INTEGER,
            processed INTEGER,
            created_at REAL,
            current_action TEXT,
            msg TEXT
        )
    ''')

    # Table: Job Results (Articles)
    c.execute('''
        CREATE TABLE IF NOT EXISTS job_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            date TEXT,
            entity TEXT,
            title TEXT,
            content TEXT,
            url TEXT,
            is_synced INTEGER DEFAULT 0,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id)
        )
    ''')

    # Table: Job Params (JSON)
    c.execute('''CREATE TABLE IF NOT EXISTS job_params (job_id TEXT PRIMARY KEY, params_json TEXT)''')

    conn.commit()
    conn.close()

# --- Job Management ---

def create_job(job_id, status="queued", total=0, processed=0, action="Initializing..."):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        INSERT INTO jobs (job_id, status, total, processed, created_at, current_action, msg)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (job_id, status, total, processed, time.time(), action, ""))
    conn.commit()
    conn.close()

def save_job_params(job_id, params_dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO job_params (job_id, params_json) VALUES (?, ?)', (job_id, json.dumps(params_dict)))
    conn.commit()
    conn.close()

def get_job_params(job_id):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute('SELECT params_json FROM job_params WHERE job_id = ?', (job_id,))
        row = c.fetchone()
        if row:
            return json.loads(row['params_json'])
    except:
        pass
    return {}

def get_next_queued_job():
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT job_id FROM jobs WHERE status = "queued" ORDER BY created_at ASC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if row:
        return row['job_id']
    return None

def update_job_progress(job_id, processed, action=None):
    conn = get_conn()
    c = conn.cursor()
    if action:
        c.execute('UPDATE jobs SET processed = ?, current_action = ? WHERE job_id = ?', (processed, action, job_id))
    else:
        c.execute('UPDATE jobs SET processed = ? WHERE job_id = ?', (processed, job_id))
    conn.commit()
    conn.close()

def update_job_status(job_id, status, msg=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE jobs SET status = ?, msg = ? WHERE job_id = ?', (status, msg, job_id))
    conn.commit()
    conn.close()

def get_job(job_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM jobs WHERE job_id = ?', (job_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

# --- Result Management ---

def save_result(job_id, date, entity, title, content, url):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        INSERT INTO job_results (job_id, date, entity, title, content, url, is_synced)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    ''', (job_id, date, entity, title, content, url))
    conn.commit()
    conn.close()

def get_job_results(job_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM job_results WHERE job_id = ?', (job_id,))
    rows = c.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "Pilih": True,
            "Tanggal": r["date"],
            "Entitas": r["entity"],
            "Judul": r["title"],
            "Isi": r["content"],
            "URL": r["url"],
            "Judul_Inggris": "",
            "Isi_Inggris": ""
        })
    return results

def get_unsynced_results(job_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM job_results WHERE job_id = ? AND is_synced = 0', (job_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_results_synced(result_ids):
    if not result_ids: return
    conn = get_conn()
    c = conn.cursor()
    placeholders = ','.join('?' * len(result_ids))
    sql = f'UPDATE job_results SET is_synced = 1 WHERE id IN ({placeholders})'
    c.execute(sql, result_ids)
    conn.commit()
    conn.close()
