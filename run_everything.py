import subprocess
import json
import re
import os
import sys
import time
import tomllib
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
    return config, facts, vetos


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
EARLY_TERMS = ("new grad", "entry", "junior", "early career", "2027", "university", "graduate",
               "associate", "rotational", "analyst i", "level 1")


def relevance(job):
    """Ordering only -- nothing is excluded here. Early-career words count only on titles
    already in the right field, or "Warehouse Associate" would outrank "Research Analyst"."""
    t = " " + (job.get("title") or "").lower() + " "
    role = sum(k in t for k in ROLE_TERMS)
    return role + (2 * sum(k in t for k in EARLY_TERMS) if role else 0)


# ------------------------------------------------------------------------------------------
# Extraction stage: the model reads, Python decides
# ------------------------------------------------------------------------------------------

EXTRACTION_PROMPT = """You extract hiring requirements from a single job posting.
Report only what the posting states. Do not infer, guess, or evaluate any candidate.

Return ONE JSON object with exactly these keys:

"employer_type": "direct_employer" | "staffing_agency" | "job_aggregator" | "bootcamp"
    job_aggregator = a platform reposting other companies' roles (e.g. Jobright, Lensa).
    staffing_agency = a recruiter or contractor placing workers at a client company.
"employment_type": "full_time" | "part_time" | "internship" | "contract" | "temporary" | "unknown"
"min_years_required": integer or null
    The MINIMUM years of professional experience the posting REQUIRES. "0-2 years" -> 0.
    "No experience required" -> 0. Experience that is "preferred", "recommended", or
    "a plus" does NOT count here. null if the posting states no requirement.
"years_preferred": integer or null
"degree_required": "none" | "bachelors" | "masters" | "phd" | null
    The minimum degree REQUIRED. A degree that is only preferred does not count.
"work_mode": "onsite" | "hybrid" | "remote" | "unknown"
"work_location": string or null   (city and state or country of the office, if any)
"work_location_in_massachusetts": true | false | null
"relocation_required": true | false
    true if the role requires moving anywhere -- INCLUDING when relocation is reimbursed,
    assisted, or appears as a listed requirement (e.g. "Relocation to the Madison, WI area").
"remote_residency_restriction": string or null
    Where a remote worker must live, e.g. "EU only", "United States", "California". null if none.
"remote_residency_allows_massachusetts": true | false | null   (null if no restriction)
"requires_security_clearance": true | false
"required_languages": list of languages OTHER than English that are REQUIRED, not preferred.
"graduation_window_start": "YYYY-MM" or null   (earliest graduation date accepted, if a cohort)
"graduation_window_end": "YYYY-MM" or null
"start_date": "immediate" | "YYYY-MM" | null
    "immediate" only if the posting explicitly says immediate or ASAP.

POSTING:
<<<
{description}
>>>
"""

DATE = re.compile(r"^\d{4}-\d{2}$")
DEGREE_RANK = {"none": 0, "bachelors": 1, "masters": 2, "phd": 3}


def extract_requirements(client, job):
    raw = call_model(client, EXTRACTION_PROMPT.format(description=job.get("full_description", "")),
                     json_mode=True, temperature=0.0)
    fields = json.loads(strip_fences(raw))
    return fields if isinstance(fields, dict) else {}


def apply_rules(f, facts, vetos):
    """Every hard rule is one explicit check on an extracted field. Returns the reasons a job
    fails; an empty list means it passes."""
    reasons = []
    grad = facts["graduation"]
    spoken = {lang.lower() for lang in facts["spoken_languages"]} | {"english"}

    employer = f.get("employer_type")
    if employer and employer != "direct_employer":
        reasons.append(f"posted by a {employer.replace('_', ' ')}")

    employment = f.get("employment_type")
    if employment not in (None, "unknown") and employment not in vetos["accepted_employment_types"]:
        reasons.append(f"{employment.replace('_', ' ')} role")

    years = f.get("min_years_required")
    if isinstance(years, (int, float)) and years > vetos["max_required_years_experience"]:
        reasons.append(f"requires {years:g}+ years of experience")

    degree = f.get("degree_required")
    if degree in DEGREE_RANK and DEGREE_RANK[degree] > DEGREE_RANK.get(facts["highest_degree"], 1):
        reasons.append(f"requires a {degree} degree")

    if f.get("relocation_required") and not facts["can_relocate"]:
        where = f" to {f['work_location']}" if f.get("work_location") else ""
        reasons.append(f"requires relocation{where}")

    mode = f.get("work_mode")
    if mode in ("onsite", "hybrid") and f.get("work_location_in_massachusetts") is False:
        reasons.append(f"{mode} outside Massachusetts ({f.get('work_location') or 'location unstated'})")
    if mode == "remote" and f.get("remote_residency_allows_massachusetts") is False:
        reasons.append(f"remote but restricted to {f.get('remote_residency_restriction') or 'another region'}")

    if f.get("requires_security_clearance") and not facts["has_security_clearance"]:
        reasons.append("requires a security clearance")

    missing = [lang for lang in (f.get("required_languages") or []) if lang.lower() not in spoken]
    if missing:
        reasons.append("requires " + ", ".join(missing))

    start, end = f.get("graduation_window_start"), f.get("graduation_window_end")
    start = start if isinstance(start, str) and DATE.match(start) else None
    end = end if isinstance(end, str) and DATE.match(end) else None
    if (start and grad < start) or (end and grad > end):
        reasons.append(f"targets graduates {start or '?'} to {end or '?'}")

    start_date = f.get("start_date")
    if start_date == "immediate" or (isinstance(start_date, str) and DATE.match(start_date) and start_date < grad):
        reasons.append(f"start date {start_date} is before graduation")

    return reasons


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


def main():
    print("==================================================")
    print("      INITIALIZING AI RECRUITER PIPELINE          ")
    print("==================================================")

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not found.")
        return

    config, facts, vetos = load_config()
    threshold = vetos["min_match_score_threshold"]

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
        if not is_job_seen(job["url"]) and signature not in seen_signatures:
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
        reasons = apply_rules(fields, facts, vetos)
        if reasons:
            filtered.append((job, reasons))
        else:
            eligible.append(job)

    print(f"Rules kept {len(eligible)} of {len(scraped)}.")
    for job, reasons in filtered:
        print(f"   x [{job.get('id')}] {job.get('company', '?')} | {(job.get('title') or '?')[:50]} -- {'; '.join(reasons)}")

    # --- PHASE 7: The Grader (fit only) ---
    print("\n--- PHASE 7: THE GRADER (SCORING FIT) ---")
    report_text = "No high-scoring matches found in this batch."
    passed_ids = set()

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

        # The grader never sees a URL, so it cannot pair a title with the wrong link.
        grader_jobs = [{"id": j["id"], "title": j.get("title"), "company": j.get("company"),
                        "location": j.get("location"), "requirements": j.get("requirements"),
                        "description": j.get("full_description")} for j in eligible]

        grade_prompt = f"""
    You are an elite career strategist scoring job fit for one candidate.

    Every job below has ALREADY passed hard eligibility checks performed on its full
    description: experience level, degree, employment type, location and relocation,
    residency, security clearance, languages, graduation window, and start date. Do not
    re-litigate those. Score FIT: how well the candidate's actual skills, coursework, and
    experience match what the role does day to day, and how competitive they would
    realistically be against other applicants.

    Backstop only: if you see an unmistakable hard disqualifier the checks missed -- for
    example an explicit requirement of prior full-time experience -- score that job 0.

    CANDIDATE:
    {candidate_context}

    JOBS (JSON; each has an integer "id"):
    {json.dumps(grader_jobs, indent=2)}

    Score every job from 0 to 100. Silently omit any job scoring below {threshold}.
    Sort the survivors from highest to lowest score.

    Format each survivor EXACTLY like this template. The title MUST be a Markdown link whose
    target is the token JOB_URL_<id>, using the job's integer id. Never write a URL yourself.
    Correct:   ### [Junior Data Analyst](JOB_URL_42)
    Wrong:     ### Junior Data Analyst (JOB_URL_42)

    ### [EXACT JOB TITLE](JOB_URL_<id>)

    * **Company:** 🏢 COMPANY
    * **Match Score:** 🎯 SCORE/100
    * **Category:** 📂 CATEGORY
    * **Deadline/Timeline:** ⏳ [explicit deadline, or "Rolling / ASAP. Apply immediately."]

    **🟢 PROS (Alignment):**
    * [1-2 specific reasons the candidate fits]

    **🔴 POTENTIAL HURDLES:**
    * [real gaps the candidate should prepare to address]

    **⚖️ THE VERDICT:**
    * [one sentence]

    ---

    If NO job scores {threshold} or higher, output exactly:
    "No high-scoring matches found in this batch."
    """
        report_text = call_model(client, grade_prompt, temperature=0.3).strip()

        for job in eligible:
            token = f"JOB_URL_{job['id']}"
            if token in report_text:
                report_text = report_text.replace(token, job.get("url", ""))
                passed_ids.add(job["id"])
        leftover = re.findall(r"JOB_URL_\d+", report_text)
        if leftover:
            print(f"Warning: {len(leftover)} unresolved link token(s) in report: {set(leftover)}")
    else:
        print("No jobs survived the rules; skipping the grader.")

    # --- Report ---
    below_threshold = len(eligible) - len(passed_ids)
    sections = ["# 🎯 Weekly AI Job Strategy: High-Probability Matches\n", report_text]
    if filtered:
        lines = [f"- **{j.get('title', '?')}** — {j.get('company', '?')}: {'; '.join(r)}"
                 for j, r in filtered]
        sections.append("\n---\n\n## Filtered out by hard rules\n\n" + "\n".join(lines))
    if below_threshold:
        sections.append(f"\n_{below_threshold} other job(s) met every rule but scored below "
                        f"{threshold} on fit._")
    with open("FINAL_STRATEGY.md", "w") as f:
        f.write("\n".join(sections))

    # Record outcomes: reported jobs are packaged; everything else goes on the cooldown timer.
    for job in scraped:
        url = job.get("url")
        if not url or job.get("id") in retry_ids:
            continue
        if job.get("id") in passed_ids:
            mark_job_packaged(url)
        else:
            mark_job_rejected(url)
    print(f"Grader outcome: {len(passed_ids)} passed, {below_threshold} below threshold, "
          f"{len(filtered)} filtered by rules.")

    # --- PHASE 8: Auto-fulfillment ---
    # Always runs: it also clears last week's packages, so skipping it could attach stale PDFs.
    run_script("auto_fulfiller.py")

    print("\n=======================================================")
    print(" PIPELINE COMPLETE! Report generated in FINAL_STRATEGY.md ")
    print("=======================================================")
    send_report()


if __name__ == "__main__":
    main()