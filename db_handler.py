import sqlite3
import json
import time
import os
from datetime import datetime

# Configuration
# If running in Colab with Drive mounted, we prefer to store DB there.
COLAB_DRIVE_PATH = "/content/drive/MyDrive/AutoNews_DB"
LOCAL_DB_NAME = "app.db"

def get_db_path():
    """
    Determines the best location for the SQLite database.
    1. Checks if Google Drive is mounted at /content/drive/MyDrive
    2. If yes, creates/uses a folder 'AutoNews_DB' and stores app.db there.
    3. If no, uses local 'app.db'.
    """
    if os.path.exists("/content/drive/MyDrive"):
        # We are likely in Colab with Drive mounted
        if not os.path.exists(COLAB_DRIVE_PATH):
            try:
                os.makedirs(COLAB_DRIVE_PATH, exist_ok=True)
                print(f"Created Database Folder in Drive: {COLAB_DRIVE_PATH}")
            except Exception as e:
                print(f"Warning: Could not create folder in Drive ({e}). Using local DB.")
                return LOCAL_DB_NAME

        db_path = os.path.join(COLAB_DRIVE_PATH, "app.db")
        print(f"Using Google Drive Database: {db_path}")
        return db_path
    else:
        # Local environment
        print(f"Using Local Database: {LOCAL_DB_NAME}")
        return LOCAL_DB_NAME

def get_conn():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

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
    # is_synced: 0 = False, 1 = True
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
        # Convert to format expected by frontend/API
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
    # Safely handle list of IDs
    placeholders = ','.join('?' * len(result_ids))
    sql = f'UPDATE job_results SET is_synced = 1 WHERE id IN ({placeholders})'
    c.execute(sql, result_ids)
    conn.commit()
    conn.close()
