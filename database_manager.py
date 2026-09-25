"""
Memory layer for the AI Career Agent.

The old behaviour permanently blacklisted every URL the scrapers ever touched,
which meant that by week three almost the entire live job market was invisible.
Job postings stay up for weeks; seeing one is not a reason to never look again.

This version distinguishes three states:
  - 'packaged' : an application package was generated. Never show again.
  - 'rejected' : the grader scored it below threshold. Re-check after COOLDOWN_DAYS.
  - 'seen'     : scraped but never actually evaluated. Re-check on the next run.

Backwards compatible: on first run it migrates any existing table that has a
url column, marking those rows 'seen' rather than 'rejected' -- the old blacklist recorded
URLs on sight, not after evaluation, so none of them were ever actually judged.
"""

import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = "memory_bank.db"

# How long a rejected posting stays suppressed before it is eligible again.
COOLDOWN_DAYS = 21


def _connect():
    return sqlite3.connect(DB_PATH)


def _legacy_urls(cur):
    """Pull URLs out of whatever the previous schema looked like."""
    urls = []
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for (table,) in cur.fetchall():
        if table == "job_memory":
            continue
        try:
            cur.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cur.fetchall()]
            if "url" in cols:
                cur.execute(f"SELECT url FROM {table}")
                urls.extend(r[0] for r in cur.fetchall() if r[0])
        except sqlite3.Error:
            continue
    return urls


def init_db():
    conn = _connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS job_memory (
            url            TEXT PRIMARY KEY,
            status         TEXT NOT NULL DEFAULT 'seen',
            first_seen     TEXT NOT NULL,
            last_evaluated TEXT
        )
    """)

    # Rejections record which version of the rules made them. Existing databases gain the
    # column with NULL values, which never match a real fingerprint -- so the first run on
    # this code releases every rejection made under older rules.
    cur.execute("PRAGMA table_info(job_memory)")
    if "rules_version" not in [row[1] for row in cur.fetchall()]:
        cur.execute("ALTER TABLE job_memory ADD COLUMN rules_version TEXT")

    # One-time migration from the old permanent-blacklist table.
    cur.execute("SELECT COUNT(*) FROM job_memory")
    if cur.fetchone()[0] == 0:
        legacy = _legacy_urls(cur)
        if legacy:
            now = datetime.now().isoformat()
            cur.executemany(
                "INSERT OR IGNORE INTO job_memory (url, status, first_seen, last_evaluated) "
                "VALUES (?, 'seen', ?, NULL)",
                [(u, now) for u in legacy],
            )
            print(f"[DB] Migrated {len(legacy)} URLs from the legacy blacklist as 'seen'. "
                  f"They were never actually evaluated, so they are eligible immediately.")

    conn.commit()
    conn.close()


def is_job_seen(url, rules_version=None):
    """
    True only when the job should be SKIPPED this run.

    Packaged jobs are skipped forever. Rejected jobs are skipped until the cooldown expires --
    OR immediately released if the rules have changed since they were rejected, because a
    judgement made under old rules shouldn't bury a job for weeks. Anything merely 'seen'
    was never evaluated and is fair game.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT status, last_evaluated, rules_version FROM job_memory WHERE url = ?", (url,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    status, last_evaluated, judged_under = row

    if status == "packaged":
        return True

    if status == "rejected":
        if rules_version is not None and judged_under != rules_version:
            return False
        if last_evaluated:
            try:
                when = datetime.fromisoformat(last_evaluated)
            except ValueError:
                return False
            return datetime.now() - when < timedelta(days=COOLDOWN_DAYS)

    return False


def mark_job_seen(url, status="seen", rules_version=None):
    """Record that we encountered a URL. Kept for backwards compatibility."""
    conn = _connect()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO job_memory (url, status, first_seen, last_evaluated, rules_version) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(url) DO UPDATE SET status = excluded.status, "
        "last_evaluated = excluded.last_evaluated, rules_version = excluded.rules_version",
        (url, status, now, now if status != "seen" else None, rules_version),
    )
    conn.commit()
    conn.close()


def mark_job_rejected(url, rules_version=None):
    """Not a match under the current rules. Suppressed for COOLDOWN_DAYS, or until the rules change."""
    mark_job_seen(url, status="rejected", rules_version=rules_version)


def mark_job_packaged(url):
    """An application package was generated. Never surface again."""
    mark_job_seen(url, status="packaged")


def memory_stats():
    """Returns a dict of counts by status, for logging."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) FROM job_memory GROUP BY status")
    stats = dict(cur.fetchall())
    conn.close()
    return stats