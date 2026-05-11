import sqlite3

DB_NAME = "memory_bank.db"

def init_db():
    """Creates the database and table if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_jobs (
            url TEXT PRIMARY KEY,
            date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_job_seen(url):
    """Checks if a job URL is already in the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM seen_jobs WHERE url = ?", (url,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_job_seen(url):
    """Adds a new job URL to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO seen_jobs (url) VALUES (?)", (url,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists in the database
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print("Memory Bank initialized successfully!")