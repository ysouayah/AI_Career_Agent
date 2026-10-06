from google import genai
from google.genai import types
import os
import json
import sys
import tomllib 
from resume_parser import extract_resume_text
import time

MAX_EXTRA_TITLES = 4   # titles the model may add on top of search_titles_core


def _norm_title(title):
    return " ".join(str(title or "").lower().split())


def merge_titles(core, extras, excluded):
    """Core titles first, then up to MAX_EXTRA_TITLES model titles that are new and not excluded."""
    titles, seen = [], set()
    for t in core:
        if _norm_title(t) and _norm_title(t) not in seen:
            titles.append(t.strip())
            seen.add(_norm_title(t))
    blocked = [_norm_title(x) for x in excluded if _norm_title(x)]
    added, dropped = [], []
    for t in extras:
        n = _norm_title(t)
        if not n:
            continue
        if n in seen:
            dropped.append((t, "already in the list"))
        elif any(b in n for b in blocked):
            dropped.append((t, "excluded in user_config.json"))
        elif len(added) >= MAX_EXTRA_TITLES:
            dropped.append((t, f"over the limit of {MAX_EXTRA_TITLES}"))
        else:
            added.append(t.strip())
            seen.add(n)
    return titles + added, added, dropped


def main():
    print("\n[Brainstormer] >> Analyzing candidate profile to determine search targets...")

    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
            for key, value in secrets.items():
                os.environ[key] = str(value)

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)

    # master_resume.md is the source of truth (same file the grader and fulfiller read).
    resume_text = ""
    if os.path.exists("master_resume.md"):
        with open("master_resume.md", "r", encoding="utf-8") as f:
            resume_text = f.read()
    elif os.path.exists("resume.pdf"):
        resume_text = extract_resume_text("resume.pdf")
    if not resume_text.strip():
        print("WARNING: no resume found (master_resume.md or resume.pdf); "
              "search titles will come from user_config.json alone.")
    
    preferences, config = "", {}
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r") as f:
            config = json.load(f)
        preferences = json.dumps(config, indent=2)

    # The core list is always searched; the model only adds to it.
    core_titles = config.get("search_titles_core", [])
    excluded_titles = config.get("search_titles_excluded", [])
    if not core_titles:
        print("WARNING: user_config.json has no search_titles_core; "
              f"only the model's {MAX_EXTRA_TITLES} titles will be searched.")

    client = genai.Client()

    prompt = f"""
    Analyze the following candidate profile.
    Resume: {resume_text}
    Preferences: {preferences}

    These job titles are ALREADY being searched: {json.dumps(core_titles)}

    Return a strict JSON object with two keys to guide our job scraper:
    "extra_titles": [0 to {MAX_EXTRA_TITLES} additional job titles to search for]
    "locations": [A list of 1 to 3 relevant locations, e.g., "Boston, MA", "Remote"]

    RULES FOR EXTRA TITLES:
    - Each one must come from the resume: a kind of work the candidate has actually done there
      (experience and projects, not coursework) that the titles already being searched would
      miss. If the resume supports fewer than {MAX_EXTRA_TITLES}, return fewer.
    - Do not repeat or reword a title that is already being searched.
    - Never include any of these: {json.dumps(excluded_titles)}
    - These are SEARCH QUERIES for job boards, not descriptions of the candidate.
      Use the literal phrasing employers put in job titles.
    - Do NOT include seniority markers like Senior, Staff, Principal, Lead, or Manager.
    - Search only for the employment types in hard_vetos.accepted_employment_types. If that
      is full-time only, do NOT include Intern, Internship, Co-op, Part-time, or Summer in any
      title -- the candidate cannot accept those, and each one wastes a search.
    """

    max_retries = 5
    for attempt in range(max_retries):
        try:
            # Forcing native JSON mode at the API level
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
            
            # Since it's native JSON, we can load it directly without text replacement hacks
            targets = json.loads(response.text.strip())
            
            extras = targets.pop("extra_titles", None)
            if not isinstance(extras, list):
                raise ValueError("AI response structure is missing the extra_titles list.")
            targets["titles"], added, dropped = merge_titles(core_titles, extras, excluded_titles)
            for title, why in dropped:
                print(f"[Brainstormer] >> Dropped model title '{title}' ({why}).")
            print(f"[Brainstormer] >> {len(core_titles)} core titles + {len(added)} from the resume: {added}")

            if not targets["titles"]:
                raise ValueError("No job titles to search: core list is empty and the model added none.")

            # Every extractor searches only the FIRST location, so it must be the candidate's
            # own city from the config, not whatever the model happened to list first.
            home = (json.loads(preferences).get("candidate_facts", {}).get("location")
                    if preferences else None)
            if home:
                others = [l for l in targets.get("locations", []) if l.lower() != home.lower()]
                targets["locations"] = [home] + others
                
            with open("search_targets.json", "w") as f:
                json.dump(targets, f, indent=4)
                
            print(f"[Brainstormer] >> Success! Targets locked: {targets['titles']} in {targets['locations']}")
            break 
            
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                wait_time = (attempt + 1) * 15 
                print(f"[!] Google API busy (Attempt {attempt+1}/{max_retries}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"\n❌ [Brainstormer] FATAL ERROR: Non-retriable failure.")
                print(f"Details: {e}")
                sys.exit(1)
    else:
        print("\n❌ [Brainstormer] FATAL ERROR: Max retries exceeded. Servers are completely down.")
        sys.exit(1)

if __name__ == "__main__":
    main()