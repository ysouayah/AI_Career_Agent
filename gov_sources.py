"""Shared pieces of the government job sources (usajobs_extractor.py, masscareers_extractor.py).

Both sites search loosely: a "Data Analyst" search returns "Procurement Analyst", and a MassCareers
keyword search reads the whole posting ("Policy Analyst" also found "Director of Finance"). Their
cards would crowd the 80-card Sifter, so a card is kept only when its own title carries every word
of the search title. Search is by title only, never by agency or company name."""
import json
import os
import re
import tomllib

# Words in a search title that describe the hiring track, not the job. Government titles rarely
# carry them ("New Grad Data Analyst" should still find "Data Analyst").
QUALIFIERS = {"new", "grad", "graduate", "entry", "level", "junior", "jr", "spring", "summer",
              "fall", "2026", "2027", "2028", "and", "&", "of", "the"}


def load_secrets():
    """Same as every other script: .streamlit/secrets.toml into the environment (CI sets env vars)."""
    path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(path):
        with open(path, "rb") as f:
            for key, value in tomllib.load(f).items():
                os.environ.setdefault(key, str(value))


def load_titles():
    """(titles, internship_titles) from search_targets.json, exactly what the other boards search."""
    with open("search_targets.json", "r") as f:
        data = json.load(f)
    return data.get("titles") or [], data.get("internship_titles") or []


def _words(text):
    return re.findall(r"[a-z0-9&]+", (text or "").lower())


def title_matches(search_title, card_title):
    """Every non-qualifier word of the search title appears as a word of the card title, in any
    order. A plural or "-ship" form counts ("Intern" finds "Internship", not "Internal")."""
    need = [w for w in _words(search_title) if w not in QUALIFIERS]
    have = set(_words(card_title))
    if not need:
        return False
    return all(w in have or w + "s" in have or w + "ship" in have for w in need)


def dedupe(jobs):
    """By URL. A job a full-time search found stays untagged even if an internship search found it too."""
    by_url = {}
    for job in jobs:
        if job["url"] not in by_url or not job.get("track"):
            by_url[job["url"]] = job
    return list(by_url.values())


def write_results(prefix, jobs, status):
    """Always writes both files, so a skipped source never leaves last week's jobs behind."""
    with open(f"{prefix}_jobs.json", "w") as f:
        json.dump(jobs, f, indent=4)
    with open(f"{prefix}_status.json", "w") as f:
        json.dump(status, f, indent=4)
