import subprocess
import json
import re
import os
import sys
import time
import tomllib
import hashlib
import csv
from datetime import datetime
from google import genai
from google.genai import types
from resume_parser import extract_resume_text

# Load Streamlit secrets into the environment for background runs
secrets_path = os.path.join(".streamlit", "secrets.toml")
if os.path.exists(secrets_path):
    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)
        for key, value in secrets.items():
            os.environ[key] = str(value)

# Piped output is block-buffered, which made rejection lines print after the fulfiller's output.
sys.stdout.reconfigure(line_buffering=True)

MODEL = "gemini-2.5-flash"
SIFTER_CAP = 80           # most relevant titles the Sifter is allowed to see
DEEP_SCRAPE_BUDGET = 40   # jobs selected for full-description scraping


# ------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------

def run_script(script_name):
    print(f"\n[{script_name}] >> Initiating sequence...")
    try:
        subprocess.run([sys.executable, script_name], check=True)
    except subprocess.CalledProcessError:
        print(f"!!! Error running {script_name}. Pipeline paused. !!!")
        exit(1)


def call_model(client, prompt, json_mode=False, temperature=0.2, retries=5):
    """One model call with backoff on rate limits and outages."""
    kwargs = {"temperature": temperature}
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=MODEL, contents=prompt,
                config=types.GenerateContentConfig(**kwargs))
            return response.text
        except Exception as e:
            transient = any(code in str(e) for code in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if transient and attempt < retries - 1:
                wait = 15 * (attempt + 1)
                print(f"   [!] Model busy (attempt {attempt + 1}/{retries}); retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise


def strip_fences(text):
    return (text or "").replace("```json", "").replace("```", "").strip()


def load_config():
    """Candidate facts and rules live in user_config.json, not in this file."""
    config = {}
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r") as f:
            config = json.load(f)
    facts = config.get("candidate_facts", {})
    facts.setdefault("graduation", "2027-05")
    facts.setdefault("highest_degree", "bachelors")
    facts.setdefault("spoken_languages", ["english"])
    facts.setdefault("can_relocate", False)
    facts.setdefault("has_security_clearance", False)
    vetos = config.get("hard_vetos", {})
    vetos.setdefault("accepted_employment_types", ["full_time"])
    vetos.setdefault("max_required_years_experience", 0)
    vetos.setdefault("min_match_score_threshold", 85)
    vetos.setdefault("filter_immediate_hires", True)
    report = config.get("report", {})
    report.setdefault("show_filtered_jobs", True)
    report.setdefault("show_near_misses", True)
    report.setdefault("near_miss_floor", 70)
    return config, facts, vetos, report


# ------------------------------------------------------------------------------------------
# Card stage: normalisation, location presence check, relevance ranking
# ------------------------------------------------------------------------------------------

def normalize_card(job):
    """Extractors only populate raw_text; title/company/location live inside it."""
    card = job.get("raw_text") or []
    if not job.get("title") and len(card) > 0:
        job["title"] = str(card[0]).strip()
    if not job.get("company") and len(card) > 2:
        job["company"] = str(card[2]).strip()
    if not job.get("location") and len(card) > 3:
        job["location"] = str(card[3]).strip()
    return job


# Presence check, not a blacklist: a job stays if Massachusetts or "remote" appears anywhere on
# its card. Checked across every line, because LinkedIn cards vary in length and shift fields.
MA = re.compile(r"(massachusetts|\bboston\b|,\s*ma\b)", re.I)
REMOTE = re.compile(r"\bremote\b", re.I)


def location_ok(job):
    lines = [str(x) for x in (job.get("raw_text") or [])] + [str(job.get("location") or "")]
    if any(MA.search(x) for x in lines) or any(REMOTE.search(x) for x in lines):
        return True
    # A bare "United States" is usually a nationwide or remote listing -- extraction decides.
    return any(x.strip().lower() in ("united states", "us", "usa") for x in lines)


ROLE_TERMS = ("data scien", "data analy", "machine learning", "analytics", "research analyst",
              "policy", "quantitative", "decision scien", "consult", "ai ", "ml ", "business analyst")
# "associate" is deliberately absent: at firms like ZS, Oliver Wyman, and A&M it is often a
# post-experience level, and ranking it up filled the Sifter with experienced roles.
EARLY_TERMS = ("new grad", "entry", "junior", "early career", "2027", "university", "graduate",
               "rotational", "analyst i", "level 1")


# Senior-level titles sort below everything else. Ranking, not filtering: they still reach the
# Sifter when a week is thin. Word boundaries keep "Staffing Analyst" and "Sriram" out of it.
SENIOR = re.compile(r"\b(senior|sr|staff|principal)\b", re.I)
SENIOR_PENALTY = 100


def is_senior_title(title):
    return bool(SENIOR.search(title or ""))


def relevance(job):
    """Ordering only -- nothing is excluded here. Early-career words count only on titles
    already in the right field, or "Warehouse Associate" would outrank "Research Analyst"."""
    t = " " + (job.get("title") or "").lower() + " "
    role = sum(k in t for k in ROLE_TERMS)
    score = role + (2 * sum(k in t for k in EARLY_TERMS) if role else 0)
    if is_senior_title(t):
        score -= SENIOR_PENALTY
    return score


# ------------------------------------------------------------------------------------------
# Extraction stage: the model reads, Python decides
# ------------------------------------------------------------------------------------------

EXTRACTION_PROMPT = """You extract hiring requirements from a single job posting.
The posting is for: {title} at {company}.

The page text may also contain unrelated sections -- "Similar jobs", "People also viewed", or
other listings. Ignore them. Extract ONLY from the posting for the role named above.

LinkedIn's criteria box ("Employment type", "Seniority level", "Job function") is filled in
by the poster and is often wrong. When it conflicts with the title or description, the title
and description win -- e.g. a role titled "(2027 Bachelor's/Master's graduates) Analyst" is
full-time graduate hiring even if the box says "Internship". Use the box only when the
description says nothing either way.
Report only what the posting states. Do not infer, guess, or evaluate any candidate.

Return ONE JSON object with exactly these keys:

"employer_type": "direct_employer" | "staffing_agency" | "job_aggregator" | "bootcamp"
    job_aggregator = a platform reposting other companies' roles (e.g. Jobright, Lensa).
    staffing_agency = a recruiter or contractor placing workers at a client company.
"employment_type": "full_time" | "part_time" | "internship" | "contract" | "temporary" | "unknown"
"min_years_required": integer or null
    MINIMUM years of professional experience REQUIRED. "0-2 years" -> 0. "No experience
    required" -> 0. Experience that is "preferred", "recommended", or "a plus" does NOT count.
    Years of experience with a specific TOOL (e.g. "2+ years of Python") is not professional
    experience. null if no requirement is stated.
"years_preferred": integer or null
"degree_required": "none" | "bachelors" | "masters" | "phd" | null
    The minimum degree REQUIRED. A degree that is only preferred does not count.
"work_mode": "onsite" | "hybrid" | "remote" | "unknown"
"work_locations": list of office locations named for this role, e.g. ["Boston, MA"]
"any_location_in_massachusetts": true | false | null
    true if ANY of the role's work locations is in Massachusetts.
"relocation_required": true | false
    true only if the hire MUST move. "Relocation assistance available" or "relocation
    support offered" is NOT a requirement. A listed requirement such as "Relocation to the
    Madison, WI area (reimbursed)" IS.
"remote_residency_restriction": string or null   e.g. "EU only", "United States", "California"
"remote_residency_allows_massachusetts": true | false | null   (null if no restriction)
"requires_active_clearance": true | false
    true only if the hire must ALREADY HOLD an active security clearance at hire.
"requires_clearance_eligibility": true | false
    true if the hire must be able or eligible to obtain a clearance or public-trust check.
"required_languages": list of languages OTHER than English that are REQUIRED, not preferred.
"graduation_window_start": "YYYY-MM" or null
"graduation_window_end": "YYYY-MM" or null
"start_date": "immediate" | "YYYY-MM" | null
    Use "YYYY-MM" ONLY when a specific month or season is stated (Summer -> 06, Fall -> 09,
    Winter -> 01). If only a year is given, return null. "immediate" only if the posting
    explicitly says the HIRE STARTS immediately or ASAP. Rolling applications, "considered as
    they apply", or "until filled" describe the APPLICATION process, not the start date.
"hiring_track": "campus_cohort" | "immediate_hire" | "unclear"
    campus_cohort = hiring a graduating class or program that starts together later: the
    posting names a class year or graduation term ("Class of 2027", "graduating between Dec
    2026 and Jun 2027"), a named analyst/associate/rotational/development program, a fixed
    program start date, or university/campus recruiting.
    immediate_hire = filling a current opening now: the posting says the hire starts
    immediately, ASAP, or within weeks, or describes backfilling a current seat -- AND names
    no class year, program, or future cohort start.
    unclear = the posting states neither. When in doubt, use unclear.
"evidence": object
    For EVERY value that could disqualify a new graduate, add a key holding a SHORT VERBATIM
    QUOTE (under 25 words) copied exactly from the posting. Use these keys:
      employer_type, employment_type, min_years_required, degree_required,
      relocation_required, work_location, remote_residency_restriction,
      requires_active_clearance, required_languages, graduation_window, start_date,
      hiring_track
    If you cannot quote text from the posting that supports a value, do not assert it.

POSTING:
<<<
{description}
>>>
"""

DATE = re.compile(r"^\d{4}-\d{2}$")
DEGREE_RANK = {"none": 0, "bachelors": 1, "masters": 2, "phd": 3}


def extract_requirements(client, job):
    prompt = EXTRACTION_PROMPT.format(title=job.get("title", ""), company=job.get("company", ""),
                                      description=job.get("full_description", ""))
    fields = json.loads(strip_fences(call_model(client, prompt, json_mode=True, temperature=0.0)))
    return fields if isinstance(fields, dict) else {}


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def quote_found(quote, text):
    """A disqualifying claim only counts if its supporting quote really appears in the posting."""
    q = _norm(quote)
    return len(q) >= 8 and q in _norm(text)


TITLE_TECH_CAP = 79


def title_tech_missing(tech, title, candidate_text):
    """The grader names a technology from the title that the candidate lacks; Python checks both
    halves before capping -- it must really be in the title and really be absent from the
    candidate's materials. Whole-word match, so "R" doesn't hit every word containing an r."""
    if not isinstance(tech, str) or not _norm(tech):
        return False
    t = f" {_norm(tech)} "
    return t in f" {_norm(title)} " and t not in f" {_norm(candidate_text)} "


def apply_rules(f, facts, vetos, text):
    """Each hard rule is one explicit check on an extracted field, and fires ONLY when the model's
    supporting quote is verified against the posting text. Returns (reasons, unverified)."""
    evidence = f.get("evidence") or {}
    reasons, unverified = [], []

    def check(key, condition, message):
        if not condition:
            return
        quote = evidence.get(key)
        if isinstance(quote, str) and quote_found(quote, text):
            reasons.append(f'{message} — "{quote.strip()[:140]}"')
        else:
            unverified.append(message)

    grad = facts["graduation"]
    spoken = {lang.lower() for lang in facts["spoken_languages"]} | {"english"}
    in_ma = f.get("any_location_in_massachusetts")
    where = ", ".join(f.get("work_locations") or []) or "location unstated"

    employer = f.get("employer_type")
    check("employer_type", employer and employer != "direct_employer",
          f"posted by a {(employer or '').replace('_', ' ')}")

    employment = f.get("employment_type")
    check("employment_type",
          employment not in (None, "unknown") and employment not in vetos["accepted_employment_types"],
          f"{(employment or '').replace('_', ' ')} role")

    years = f.get("min_years_required")
    check("min_years_required",
          isinstance(years, (int, float)) and years > vetos["max_required_years_experience"],
          f"requires {years}+ years of experience")

    degree = f.get("degree_required")
    check("degree_required",
          degree in DEGREE_RANK and DEGREE_RANK[degree] > DEGREE_RANK.get(facts["highest_degree"], 1),
          f"requires a {degree} degree")

    # Moving to Massachusetts is not relocation for someone who already lives there.
    check("relocation_required",
          f.get("relocation_required") and not facts["can_relocate"] and in_ma is not True,
          f"requires relocation to {where}")

    mode = f.get("work_mode")
    check("work_location", mode in ("onsite", "hybrid") and in_ma is False,
          f"{mode} outside Massachusetts ({where})")
    check("remote_residency_restriction",
          mode == "remote" and f.get("remote_residency_allows_massachusetts") is False,
          f"remote but restricted to {f.get('remote_residency_restriction') or 'another region'}")

    # Only an ALREADY-HELD clearance disqualifies. Eligibility-to-obtain is normal for entry-level
    # government-contractor roles and is left for the candidate to judge.
    check("requires_active_clearance",
          f.get("requires_active_clearance") and not facts["has_security_clearance"],
          "requires an active security clearance")

    missing = [lang for lang in (f.get("required_languages") or []) if lang.lower() not in spoken]
    check("required_languages", bool(missing), "requires " + ", ".join(missing))

    ws, we = f.get("graduation_window_start"), f.get("graduation_window_end")
    ws = ws if isinstance(ws, str) and DATE.match(ws) else None
    we = we if isinstance(we, str) and DATE.match(we) else None
    check("graduation_window", bool((ws and grad < ws) or (we and grad > we)),
          f"targets graduates {ws or '?'} to {we or '?'}")

    sd = f.get("start_date")
    check("start_date",
          sd == "immediate" or (isinstance(sd, str) and bool(DATE.match(sd)) and sd < grad),
          f"start date {sd} is before graduation")

    # A seat being filled now will be gone long before a Spring graduate can start. Like every
    # other rule, it only fires on a verified quote; "unclear" postings go through.
    check("hiring_track",
          vetos["filter_immediate_hires"] and f.get("hiring_track") == "immediate_hire",
          "immediate hire, not a new-grad cohort")

    return reasons, unverified


TRACK_LABELS = {"campus_cohort": "🎓 Campus cohort", "immediate_hire": "⚡ Immediate hire",
                "unclear": "❔ Unclear"}


def track_label(job):
    track = (job.get("requirements") or {}).get("hiring_track")
    return TRACK_LABELS.get(track, TRACK_LABELS["unclear"])


# ------------------------------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------------------------------

def send_report():
    if os.environ.get("EMAIL_USER") and os.environ.get("EMAIL_PASS"):
        try:
            from notifier import send_strategy_report
            send_strategy_report(os.environ.get("EMAIL_USER"))
        except ImportError:
            print("Notice: notifier.py not found. Skipping email dispatch.")


# One row per job the pipeline evaluated, appended every run. This is the raw material for the
# evaluation tracker (update_tracker.py): the agent's decision next to your own verdict.
RUN_LOG = "agent_log.csv"
RUN_LOG_FIELDS = ["run_date", "company", "title", "location", "decision", "score", "reason",
                  "hiring_track", "rules_version", "url"]


def append_run_log(rows):
    new_file = not os.path.exists(RUN_LOG)
    with open(RUN_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def main():
    print("==================================================")
    print("      INITIALIZING AI RECRUITER PIPELINE          ")
    print("==================================================")

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not found.")
        return

    config, facts, vetos, report = load_config()
    threshold = vetos["min_match_score_threshold"]

    # Fingerprint of the rules: this file's code plus the candidate facts and vetos. When any
    # of it changes, rejections made under the old version are released automatically.
    with open(os.path.abspath(__file__), "rb") as f:
        code = f.read()
    rules_version = hashlib.sha1(
        code + json.dumps([facts, vetos], sort_keys=True).encode()).hexdigest()[:10]
    print(f"Rules version: {rules_version}")

    # --- PHASE 1 and 2: Brainstorm & Surface Scrape ---
    run_script("brainstormer.py")

    print("\n--- DEPLOYING EXTRACTION FLEET ---")
    run_script("handshake_extractor.py")
    run_script("linkedin_extractor.py")
    run_script("indeed_extractor.py")

    # --- PHASE 3: Compile, deduplicate, check memory ---
    print("\n--- COMPILING & FILTERING JOB DATA ---")
    from database_manager import init_db, is_job_seen, mark_job_rejected, mark_job_packaged, memory_stats
    init_db()

    raw_jobs = []
    for file in ["handshake_jobs.json", "linkedin_jobs.json", "indeed_jobs.json"]:
        if os.path.exists(file):
            with open(file, "r") as f:
                raw_jobs.extend(json.load(f))
    print(f"Total raw jobs scraped: {len(raw_jobs)}")

    fresh_jobs, seen_signatures, collapsed = [], set(), 0
    for job in raw_jobs:
        normalize_card(job)
        company = (job.get("company") or "").strip()
        title = (job.get("title") or "").strip()
        signature = f"{company}_{title}".lower().strip("_")
        if not signature:
            # A shared placeholder signature would collapse every job into one bucket.
            signature = job["url"]
            collapsed += 1
        if not is_job_seen(job["url"], rules_version) and signature not in seen_signatures:
            fresh_jobs.append(job)
            seen_signatures.add(signature)

    print(f"Total FRESH jobs for evaluation: {len(fresh_jobs)}")
    if collapsed:
        print(f"Note: {collapsed} jobs had no recoverable company/title; deduplicated by URL instead.")
    print(f"Memory state: {memory_stats()}")

    if not fresh_jobs:
        with open("FINAL_STRATEGY.md", "w") as f:
            f.write("# 🎯 Weekly AI Job Strategy\n\nNo new jobs were found by the scrapers this week.")
        send_report()
        return

    # --- Card stage: location presence check, then relevance ordering ---
    before = len(fresh_jobs)
    fresh_jobs = [j for j in fresh_jobs if location_ok(j)]
    print(f"Location check kept {len(fresh_jobs)} of {before} (Massachusetts or remote on the card).")
    if not fresh_jobs:
        with open("FINAL_STRATEGY.md", "w") as f:
            f.write("# 🎯 Weekly AI Job Strategy\n\nNo Massachusetts or remote jobs were found this week.")
        send_report()
        return

    fresh_jobs.sort(key=relevance, reverse=True)
    if len(fresh_jobs) > SIFTER_CAP:
        print(f"Capping Sifter input to the {SIFTER_CAP} most relevant of {len(fresh_jobs)} titles.")
        fresh_jobs = fresh_jobs[:SIFTER_CAP]

    # Each job carries an integer id. Models return ids only and never copy a URL, because
    # LLMs mis-pair fields when transcribing large arrays.
    for i, j in enumerate(fresh_jobs):
        j["id"] = i

    client = genai.Client()

    # --- PHASE 4: The Sifter (ranking only) ---
    print("\n--- PHASE 4: THE SIFTER (SELECTING TARGETS) ---")
    if len(fresh_jobs) <= DEEP_SCRAPE_BUDGET:
        print(f"Only {len(fresh_jobs)} eligible jobs -- skipping the Sifter and deep-scraping all.")
        sifted_jobs = list(fresh_jobs)
    else:
        cards = [{"id": j["id"], "title": j.get("title", ""), "company": j.get("company", ""),
                  "location": j.get("location", "")} for j in fresh_jobs]
        interests = config.get("industry_rubric", {})
        sift_prompt = f"""
    You are ranking job search results for a candidate.

    CANDIDATE: Spring 2027 graduate, dual degree in Data Science and Political Science.
    Interests: {', '.join(interests.get('primary_focus', []))}; also
    {', '.join(interests.get('secondary_interdisciplinary_focus', []))}.
    Seeking full-time roles starting after graduation.

    These are SEARCH RESULT PREVIEW CARDS, not full descriptions. A later stage reads every
    selected posting in full and enforces all eligibility rules, so do not filter on anything --
    seniority, location, or company type. YOUR ONLY JOB IS RANKING by how well the title fits
    the candidate's field, preferring titles that signal early-career or new-graduate hiring.
    The candidate wants FULL-TIME roles: rank internships, co-ops, and roles aimed at current
    Master's, MBA, or PhD students below full-time positions for bachelor's graduates.
    Rank any title containing Senior, Sr., Staff, or Principal LAST -- below every other
    title, including weaker-fit ones. Include them only if you need them to reach the count.

    Return EXACTLY {DEEP_SCRAPE_BUDGET} ids. A later stage checks each one properly, so a weak
    pick costs little and an omitted good job is lost entirely.

    Jobs: {json.dumps(cards, indent=2)}

    Output ONLY a JSON array of integer ids, e.g. [3, 17, 204]. No markdown, no commentary.
    """
        try:
            chosen_ids = json.loads(strip_fences(call_model(client, sift_prompt, temperature=0.3)))
            by_id = {j["id"]: j for j in fresh_jobs}
            sifted_jobs = [by_id[i] for i in chosen_ids if isinstance(i, int) and i in by_id]
            unknown = len(chosen_ids) - len(sifted_jobs)
            if unknown:
                print(f"Warning: Sifter returned {unknown} unknown id(s); ignored.")
        except Exception as e:
            print(f"Error parsing Sifter output: {e}")
            return

    with open("sifted_jobs.json", "w") as f:
        json.dump(sifted_jobs, f, indent=4)
    print(f"Sifter kept {len(sifted_jobs)} of {len(fresh_jobs)} jobs for deep scraping.")
    for j in sifted_jobs:
        print(f"   -> [{j['id']}] {j.get('company', '?')} | {(j.get('title') or '?')[:60]} | {j.get('location', '?')}")

    # --- PHASE 5: The Deep Scrape ---
    run_script("deep_scraper.py")
    if not os.path.exists("deep_jobs.json"):
        print("No deep scraped data found. Ending pipeline.")
        return
    with open("deep_jobs.json", "r") as f:
        scraped = json.load(f)

    # --- PHASE 6: Extraction + deterministic rules ---
    print("\n--- PHASE 6: EXTRACTING REQUIREMENTS & APPLYING RULES ---")
    eligible, filtered = [], []
    retry_ids = set()   # transient failures: left unmarked so the next run tries again
    for job in scraped:
        description = job.get("full_description") or ""
        if "no longer accepting applications" in description.lower():
            filtered.append((job, ["no longer accepting applications"]))
            continue
        if len(description) < 500:
            filtered.append((job, ["description could not be scraped (will retry next run)"]))
            retry_ids.add(job.get("id"))
            continue
        try:
            fields = extract_requirements(client, job)
        except Exception as e:
            print(f"   [!] Extraction failed for [{job.get('id')}]: {e}")
            filtered.append((job, ["requirements could not be extracted (will retry next run)"]))
            retry_ids.add(job.get("id"))
            continue
        job["requirements"] = fields
        reasons, unverified = apply_rules(fields, facts, vetos, description)
        if unverified:
            print(f"   ? [{job.get('id')}] {(job.get('title') or '?')[:45]} -- unverified, NOT applied: "
                  f"{'; '.join(unverified)}")
        if reasons:
            filtered.append((job, reasons))
        else:
            eligible.append(job)

    print(f"Rules kept {len(eligible)} of {len(scraped)}.")
    for job, reasons in filtered:
        print(f"   x [{job.get('id')}] {job.get('company', '?')} | {(job.get('title') or '?')[:50]} -- {'; '.join(reasons)}")

    # --- PHASE 7: The Grader -- the model scores, Python applies the threshold ---
    print("\n--- PHASE 7: THE GRADER (SCORING FIT) ---")
    approved, near_misses, scores = [], [], {}
    writeups = ""

    if eligible:
        candidate_context = "--- MASTER RESUME ---\n"
        if os.path.exists("master_resume.md"):
            with open("master_resume.md", "r", encoding="utf-8") as f:
                candidate_context += f.read()
        elif os.path.exists("resume.pdf"):
            candidate_context += extract_resume_text("resume.pdf")
        else:
            print("WARNING: no resume source found. Grading will be unreliable.")
        if os.path.exists("transcript.pdf"):
            candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n" + extract_resume_text("transcript.pdf")
        rubric = config.get("industry_rubric", {})
        candidate_context += (
            f"\n\n--- INTERESTS ---\nPrimary: {', '.join(rubric.get('primary_focus', []))}\n"
            f"Interdisciplinary: {', '.join(rubric.get('secondary_interdisciplinary_focus', []))}\n"
            f"Preferred stack: {', '.join(rubric.get('preferred_tech_stack', []))}\n")

        # The model never sees a URL, so it cannot pair a title with the wrong link.
        grader_jobs = [{"id": j["id"], "title": j.get("title"), "company": j.get("company"),
                        "location": j.get("location"), "requirements": j.get("requirements"),
                        "description": j.get("full_description")} for j in eligible]

        # Step 1: a score and a one-line reason for EVERY eligible job.
        score_prompt = f"""
    You are an elite career strategist scoring job fit for one candidate.

    Every job below has ALREADY passed hard eligibility checks performed on its full
    description: experience level, degree, employment type, location and relocation,
    residency, security clearance, languages, graduation window, and start date. Do not
    re-litigate those. Score FIT from 0 to 100: how well the candidate's actual skills,
    coursework, and experience match what the role does day to day, and how competitive they
    would realistically be. Weigh the candidate's policy and political-science background as
    seriously as the technical one.

    CALIBRATION -- these numbers mean specific things. Use them as anchors:
      90-100  COMPETITIVE. The candidate's record covers the core of what this role does day
              to day, and a hiring team would plausibly put them in the interview pool against
              other strong new-grad applicants. A good-but-ordinary fit is not a 90.
      85-89   Strong fit with one real gap the candidate can credibly address.
      70-84   Plausible stretch: adjacent skills, or a core requirement only partly evidenced.
      0-69    Weak fit.
    TITLE TECHNOLOGY: if the job title names a specific tool, platform, or language (e.g.
    "Salesforce Analyst", "Snowflake Data Engineer", "SAP Business Analyst", "Power BI
    Developer") and the candidate's materials do not show it, the score MUST stay in the 70s
    at most, however well everything else fits. Name that technology in "missing_title_tech"
    exactly as it appears in the title; otherwise use null.

    Backstop only: if you see an unmistakable hard disqualifier the checks missed -- for example
    an explicit requirement of prior full-time experience -- score that job 0.

    CANDIDATE:
    {candidate_context}

    JOBS (JSON; each has an integer "id"):
    {json.dumps(grader_jobs, indent=2)}

    Return ONLY a JSON array with one object per job:
    [{{"id": 3, "score": 88, "reason": "one sentence on the deciding factor",
      "missing_title_tech": null}}]
    """
        by_id = {j["id"]: j for j in eligible}
        try:
            rows = json.loads(strip_fences(call_model(client, score_prompt, json_mode=True, temperature=0.2)))
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), int):
                    score, reason = int(row.get("score", 0)), str(row.get("reason", "")).strip()
                    tech = row.get("missing_title_tech")
                    title = (by_id.get(row["id"]) or {}).get("title") or ""
                    if score > TITLE_TECH_CAP and title_tech_missing(tech, title, candidate_context):
                        reason = f"[capped from {score}: title names {tech.strip()}, not on resume] {reason}"
                        score = TITLE_TECH_CAP
                    scores[row["id"]] = (score, reason)
        except Exception as e:
            print(f"Error parsing grader scores: {e}")

        for jid, (score, reason) in sorted(scores.items(), key=lambda kv: -kv[1][0]):
            if jid not in by_id:
                continue
            if score >= threshold:
                approved.append(by_id[jid])
            elif score >= report["near_miss_floor"]:
                near_misses.append((by_id[jid], score, reason))
        unscored = [j for j in eligible if j["id"] not in scores]
        if unscored:
            print(f"Warning: grader returned no score for {len(unscored)} job(s): "
                  f"{[j['id'] for j in unscored]}")

        for j in eligible:
            if j["id"] in scores:
                sc, why = scores[j["id"]]
                print(f"   {sc:>3} [{j['id']}] {(j.get('company') or '?')[:22]} | {(j.get('title') or '?')[:45]} -- {why[:90]}")

        # Step 2: full write-ups, only for jobs Python approved, using Python's scores.
        if approved:
            writeup_jobs = [dict(g, score=scores[g["id"]][0], hiring_track=track_label(by_id[g["id"]]))
                            for g in grader_jobs if g["id"] in {a["id"] for a in approved}]
            writeup_prompt = f"""
    Write the report entries for these jobs. They have already been scored; use each job's
    "score" field EXACTLY as given and do not re-score. Keep them in the order given.

    CANDIDATE:
    {candidate_context}

    JOBS (JSON; each has an integer "id" and a "score"):
    {json.dumps(sorted(writeup_jobs, key=lambda g: -g["score"]), indent=2)}

    Format each job EXACTLY like this template. The title MUST be a Markdown link whose target
    is the token JOB_URL_<id>, using the job's integer id. Never write a URL yourself.
    Correct:   ### [Junior Data Analyst](JOB_URL_42)
    Wrong:     ### Junior Data Analyst (JOB_URL_42)

    ### [EXACT JOB TITLE](JOB_URL_<id>)

    * **Company:** 🏢 COMPANY
    * **Match Score:** 🎯 SCORE/100
    * **Category:** 📂 CATEGORY
    * **Hiring Track:** [the job's "hiring_track" value, copied verbatim]
    * **Deadline/Timeline:** ⏳ [explicit deadline, or "Rolling / ASAP. Apply immediately."]

    **🟢 PROS (Alignment):**
    * [1-2 specific reasons the candidate fits]

    **🔴 POTENTIAL HURDLES:**
    * [real gaps the candidate should prepare to address]

    **⚖️ THE VERDICT:**
    * [one sentence]

    ---
    """
            writeups = call_model(client, writeup_prompt, temperature=0.3).strip()
            for job in approved:
                writeups = writeups.replace(f"JOB_URL_{job['id']}", job.get("url", ""))
            leftover = re.findall(r"JOB_URL_\d+", writeups)
            if leftover:
                print(f"Warning: {len(leftover)} unresolved link token(s) in report: {set(leftover)}")
    else:
        print("No jobs survived the rules; skipping the grader.")

    # The explicit hand-off to the fulfiller. It reads this list rather than scanning the
    # report for URLs, so near-miss links in the email never trigger package generation.
    with open("approved_jobs.json", "w") as f:
        json.dump(approved, f, indent=4)

    # Near misses are saved with a label (N1, N2, ...) so a package can be generated on request:
    #   python auto_fulfiller.py --near-miss N2 N5
    # Always rewritten, so a label can never point at last week's job.
    near_miss_records = [dict(j, near_miss_label=f"N{k}", score=sc, reason=why)
                         for k, (j, sc, why) in enumerate(near_misses, start=1)]
    with open("near_miss_jobs.json", "w") as f:
        json.dump(near_miss_records, f, indent=4)

    # --- Report ---
    sections = ["# 🎯 Weekly AI Job Strategy: High-Probability Matches\n",
                writeups or "No high-scoring matches found in this batch."]
    if report["show_near_misses"] and near_misses:
        lines = [f"- `{r['near_miss_label']}` **[{r.get('title', '?')}]({r.get('url', '')})** — "
                 f"{r.get('company', '?')} · {track_label(r)}: {r['score']}/100. {r['reason']}"
                 for r in near_miss_records]
        sections.append(f"\n---\n\n## Worth a look ({report['near_miss_floor']}–{threshold - 1})\n\n"
                        + "\n".join(lines)
                        + "\n\n_Want a package for one of these? Run "
                          "`python auto_fulfiller.py --near-miss N1 N3` (or `all`)._")
    below = len(eligible) - len(approved) - len(near_misses)
    if below > 0:
        sections.append(f"\n_{below} other eligible job(s) scored below {report['near_miss_floor']}._")
    if report["show_filtered_jobs"] and filtered:
        lines = [f"- **{j.get('title', '?')}** — {j.get('company', '?')}: {'; '.join(r)}"
                 for j, r in filtered]
        sections.append("\n---\n\n## Filtered out by hard rules\n\n" + "\n".join(lines))
    with open("FINAL_STRATEGY.md", "w") as f:
        f.write("\n".join(sections))

    # Record outcomes: approved jobs are packaged; everything else goes on the cooldown timer.
    approved_ids = {j["id"] for j in approved}
    for job in scraped:
        url = job.get("url")
        if not url or job.get("id") in retry_ids:
            continue
        if job.get("id") in approved_ids:
            mark_job_packaged(url)
        else:
            mark_job_rejected(url, rules_version)
    # Log every evaluated job with the stage that decided it.
    run_date = datetime.now().strftime("%Y-%m-%d")
    near_ids = {j["id"] for j, _, _ in near_misses}
    filter_reasons = {j.get("id"): r for j, r in filtered}
    log_rows = []
    for job in scraped:
        jid = job.get("id")
        score, reason = "", ""
        if jid in filter_reasons:
            decision = "retry" if jid in retry_ids else "filtered"
            reason = "; ".join(filter_reasons[jid])
        elif jid in scores:
            score, reason = scores[jid]
            decision = ("approved" if jid in approved_ids else
                        "near_miss" if jid in near_ids else "below_floor")
        else:
            decision = "unscored"
        log_rows.append({
            "run_date": run_date, "company": job.get("company") or "", "title": job.get("title") or "",
            "location": job.get("location") or "", "decision": decision, "score": score,
            "reason": reason, "hiring_track": (job.get("requirements") or {}).get("hiring_track") or "",
            "rules_version": rules_version, "url": job.get("url") or "",
        })
    append_run_log(log_rows)

    print(f"Grader outcome: {len(approved)} approved, {len(near_misses)} near-miss, "
          f"{max(below, 0)} below {report['near_miss_floor']}, {len(filtered)} filtered by rules.")

    # --- PHASE 8: Auto-fulfillment ---
    # Always runs: it also clears last week's packages, so skipping it could attach stale PDFs.
    run_script("auto_fulfiller.py")

    print("\n=======================================================")
    print(" PIPELINE COMPLETE! Report generated in FINAL_STRATEGY.md ")
    print("=======================================================")
    send_report()


if __name__ == "__main__":
    main()