import subprocess
import json
import re
import collections
import os
from google import genai
from google.genai import types
from resume_parser import extract_resume_text
import sys
import tomllib

# Load Streamlit secrets into the environment for background runs
secrets_path = os.path.join(".streamlit", "secrets.toml")
if os.path.exists(secrets_path):
    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)
        for key, value in secrets.items():
            os.environ[key] = str(value)

def url_matches(url, text):
    """Job boards append tracking params, and the model often drops them when
    copying a URL into the report. Match on the bare URL, then on the numeric
    job ID, before giving up."""
    if not url:
        return False
    base = url.split("?")[0].split("#")[0].rstrip("/")
    if base and base in text:
        return True
    if url in text:
        return True
    for job_id in re.findall(r"\d{6,}", base):
        if job_id in text:
            return True
    return False


def run_script(script_name):
    print(f"\n[{script_name}] >> Initiating sequence...")
    try:
        subprocess.run([sys.executable, script_name], check=True) 
    except subprocess.CalledProcessError:
        print(f"!!! Error running {script_name}. Pipeline paused. !!!")
        exit(1)

def main():
    print("==================================================")
    print("      INITIALIZING AI RECRUITER PIPELINE          ")
    print("==================================================")

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not found.")
        return

    # --- PHASE 1 and 2: Brainstorm & Surface Scrape ---
    run_script("brainstormer.py")
    
    print("\n--- DEPLOYING EXTRACTION FLEET ---")
    run_script("handshake_extractor.py")
    run_script("linkedin_extractor.py")
    run_script("indeed_extractor.py")

    # --- PHASE 3: Compiling the Data & Checking Memory ---
    print("\n--- COMPILING & FILTERING JOB DATA ---")
    from database_manager import (init_db, is_job_seen, mark_job_seen,
                                  mark_job_rejected, mark_job_packaged, memory_stats)
    
    init_db()
    
    raw_jobs = []
    for file in ["handshake_jobs.json", "linkedin_jobs.json", "indeed_jobs.json"]:
        if os.path.exists(file):
            with open(file, "r") as f:
                raw_jobs.extend(json.load(f))
                
    print(f"Total raw jobs scraped: {len(raw_jobs)}")
    
    fresh_jobs = []
    seen_signatures = set() # Tracks Company + Title combos to kill ATS spam
    
    def _normalize(job):
        """Extractors only populate raw_text; title/company/location live inside it."""
        card = job.get("raw_text") or []
        if not job.get("title") and len(card) > 0:
            job["title"] = str(card[0]).strip()
        if not job.get("company") and len(card) > 2:
            job["company"] = str(card[2]).strip()
        if not job.get("location") and len(card) > 3:
            job["location"] = str(card[3]).strip()
        return job

    collapsed = 0
    for job in raw_jobs:
        _normalize(job)

        company = (job.get("company") or "").strip()
        title = (job.get("title") or "").strip()
        signature = f"{company}_{title}".lower().strip("_")

        # If we could not recover a real company/title, fall back to the URL.
        # A shared placeholder signature would collapse every job into one bucket.
        if not signature:
            signature = job["url"]
            collapsed += 1
        
        # Only process if the URL is new AND the Company+Title combo hasn't been seen today
        if not is_job_seen(job['url']) and signature not in seen_signatures:
            fresh_jobs.append(job)
            seen_signatures.add(signature)

    print(f"Total FRESH jobs for evaluation: {len(fresh_jobs)}")
    if collapsed:
        print(f"Note: {collapsed} jobs had no recoverable company/title; "
              f"deduplicated by URL instead.")
    print(f"Memory state: {memory_stats()}")
    
    if len(fresh_jobs) == 0:
        print("No new jobs found this week. Bypassing AI Grader and sending status email.")
        with open("FINAL_STRATEGY.md", "w") as f:
            f.write("# 🎯 Weekly AI Job Strategy\n\nNo new fresh jobs were found by the scrapers this week. Keep refining the search queries!")
        
        # Trigger the email even if empty
        if os.environ.get("EMAIL_USER") and os.environ.get("EMAIL_PASS"):
            try:
                from notifier import send_strategy_report
                send_strategy_report(os.environ.get("EMAIL_USER"))
            except ImportError:
                pass
        return

    # The Sifter only ever sees preview cards, so send just the usable fields.

    # --- DETERMINISTIC PRE-FILTER ---------------------------------------------------
    # Every rule here is visible on the card, so Python applies it exactly. Handing 800+
    # cards to a model and asking it to enforce rules produced picks in Canada, a
    # "Lead Scientist", and four postings from a job aggregator.
    SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|"
                        r"vp|vice president|architect|iii|iv)\b", re.I)
    INTERN = re.compile(r"\b(intern|internship|co-?op|summer analyst|fellowship)\b", re.I)
    BLOCKED = ("jobright", "synergisticit", "revature", "fdm group", "lensa",
               "jobs via dice", "hiring cafe")

    # Remote postings usually show the company's HQ city on the card, so a US city
    # outside Massachusetts does NOT mean the role is on-site elsewhere. Only reject what
    # the card makes certain: non-US postings. Gate 9 reads the full JD for everything else.
    FOREIGN = re.compile(r"\b(canada|ontario|toronto|vancouver|montreal|quebec|united kingdom|"
                         r"england|london|ireland|dublin|india|bengaluru|bangalore|hyderabad|"
                         r"pune|germany|berlin|france|netherlands|amsterdam|spain|poland|"
                         r"singapore|australia|mexico|brazil|philippines|israel|emea|apac)\b", re.I)

    def _location_ok(loc):
        return not FOREIGN.search(loc or "")

    reasons = {"senior": 0, "intern": 0, "location": 0, "blocked": 0}
    rejected_locs = collections.Counter()
    eligible = []
    for j in fresh_jobs:
        title = j.get("title", "") or ""
        company = (j.get("company", "") or "").lower()
        if any(b in company for b in BLOCKED):
            reasons["blocked"] += 1
        elif INTERN.search(title):
            reasons["intern"] += 1
        elif SENIOR.search(title):
            reasons["senior"] += 1
        elif not _location_ok(j.get("location")):
            reasons["location"] += 1
            rejected_locs[j.get("location")] += 1
        else:
            eligible.append(j)
    print(f"Pre-filter kept {len(eligible)} of {len(fresh_jobs)}. Removed: {reasons}")
    if rejected_locs:
        print(f"   Top rejected locations: {rejected_locs.most_common(8)}")
    fresh_jobs = eligible

    if not fresh_jobs:
        print("Pre-filter removed every job. Nothing to sift.")
        return

    ROLE = ("data scien", "data analy", "machine learning", "analytics", "research analyst",
            "policy", "quantitative", "decision scien", "consult", "ai ", "ml ", "business analyst")
    EARLY = ("new grad", "entry", "junior", "early career", "2027", "university", "graduate",
             "associate", "rotational", "analyst i", "level 1")

    def _relevance(job):
        t = " " + (job.get("title") or "").lower() + " "
        role = sum(k in t for k in ROLE)
        # Early-career words only count on titles that are already in the right field --
        # otherwise "Warehouse Associate" outranks "Research Analyst".
        return role + (2 * sum(k in t for k in EARLY) if role else 0)

    SIFTER_CAP = 80
    fresh_jobs.sort(key=_relevance, reverse=True)
    if len(fresh_jobs) > SIFTER_CAP:
        print(f"Capping Sifter input to the {SIFTER_CAP} most relevant of {len(fresh_jobs)} titles.")
        fresh_jobs = fresh_jobs[:SIFTER_CAP]

    # Each card carries an integer id. The model returns ids only -- it never copies a URL,
    # because LLMs reliably mis-pair fields when transcribing large arrays.
    for i, j in enumerate(fresh_jobs):
        j["id"] = i
    sifter_cards = [
        {"id": j["id"], "title": j.get("title", ""),
         "company": j.get("company", ""), "location": j.get("location", ""),
         "source": j.get("source", "")}
        for j in fresh_jobs
    ]
    jobs_str = json.dumps(sifter_cards, indent=2)

    # --- DYNAMIC CONTEXT BUILDING ---
    candidate_context = "--- MASTER RESUME ---\n"
    if os.path.exists("master_resume.md"):
        with open("master_resume.md", "r", encoding="utf-8") as f:
            candidate_context += f.read()
    elif os.path.exists("resume.pdf"):
        candidate_context += extract_resume_text("resume.pdf")
    else:
        print("WARNING: no resume source found. Grading will be unreliable.")

    if os.path.exists("transcript.pdf"):
        candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n"
        candidate_context += extract_resume_text("transcript.pdf")

    candidate_context += "\n\n--- EXPLICIT CANDIDATE PREFERENCES & GRADING RUBRIC ---\n"
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r") as f:
            config = json.load(f)
        
        if config['hard_vetos'].get('reject_standard_immediate_hire_requisitions'):
            req_veto = ("Instantly reject any standard corporate job posting that lacks a "
                        "future cohort target, even if labeled entry-level.")
        else:
            req_veto = ("DISABLED. Do NOT reject a role merely because it lacks an explicit "
                        "graduation-cohort marker. Many legitimate new-grad roles never use "
                        "that phrasing. Judge such roles on the rest of the rubric, and reject "
                        "them only if they demand professional experience the candidate lacks.")

        candidate_context += f"""
        1. THE DUAL-TIMELINE RULE: Evaluate jobs against two strictly acceptable pathways. If a job fits EITHER pathway, it passes.
        - Pathway A ({config['target_timelines']['pathway_a']['type']}): Target window is {config['target_timelines']['pathway_a']['target_window']}.
        - Pathway B ({config['target_timelines']['pathway_b']['type']}): Only accept full-time roles explicitly mentioning a cohort target or graduation marker like {', '.join(config['target_timelines']['pathway_b']['cohort_keywords'])}.
        
        2. THE TECHNICAL & DOMAIN ALIGNMENT: 
        - Prioritize engineering stacks utilizing: {', '.join(config['industry_rubric']['preferred_tech_stack'])}.
        - Look for intersections between {', '.join(config['industry_rubric']['primary_focus'])} and core analytical work in {', '.join(config['industry_rubric']['secondary_interdisciplinary_focus'])}.
        
        3. THE STANDARD REQ VETO: 
        - {req_veto}
        
        4. THE STRICT SENIORITY KILL SWITCH:
        - Actively scan the job description for implicit senior-level requirements. Even if the job does not explicitly ask for years of experience, you MUST score the job below 50/100 and flag it as a mismatch if it requires any of the following without explicitly stating it is a training, junior, or new-grad role:
          * "End-to-end technical ownership" of enterprise systems or customer engagements.
          * "Production at scale" or maintaining live, large-scale architectures independently.
          * Serving as the "lead," "principal," or primary "technical owner" for stakeholders.
        """
    else:
        candidate_context += "Evaluate jobs based on general professional fit, standard industry entry requirements, and alignment with the provided resume skills."

    client = genai.Client()

    # --- PHASE 4: The Sifter (Holistic Alignment Protocol) ---
    print("\n--- PHASE 4: THE SIFTER (SELECTING TARGETS) ---")
    sifter_profile = (
        "CANDIDATE: Spring 2027 graduate, dual degree in Data Science and Political Science. "
        "Background in Python, SQL, R, Tableau, machine learning coursework, data pipelines, "
        "LLM applications, policy research, and analytics consulting. Based in Boston, MA and "
        "cannot relocate. Seeking full-time roles starting after graduation, or part-time and "
        "contract work during the academic year."
    )

    sift_prompt = f"""
    You are triaging job listings for the candidate described below.

    {sifter_profile}

    CRITICAL CONTEXT ABOUT YOUR INPUT:
    You are being shown SEARCH RESULT PREVIEW CARDS, not full job descriptions. Each card has
    only a title, company, location, and source. You CANNOT see requirements, years of
    experience, tech stack, languages, or graduation cohorts. A later stage scrapes the full
    description and applies the strict rubric.

    Every card below has ALREADY passed hard filters for seniority, internships, location,
    and blocked companies. Do not re-filter on those grounds. YOUR ONLY JOB IS RANKING:
    choose the cards whose titles best fit the candidate.

    REJECT a card only when one of these is visible on its face:
    1. The title contains "Intern", "Internship", "Co-op", "Summer Analyst", or "Fellowship".
    2. The title contains a seniority marker: Senior, Sr., Staff, Principal, Lead, Manager,
       Director, Head of, VP, Architect, or roman numerals III+.
    3. The title requires a degree the candidate does not have (e.g. "PhD Required", "MD", "JD").
    4. The location is clearly outside commuting distance of Boston, MA and is not marked
       Remote. Massachusetts locations and "Remote" are acceptable. Cards listing several
       cities including Boston are acceptable.
    5. The company is a known resume farm or pay-to-play bootcamp (SynergisticIT, Revature,
       FDM Group). Legitimate consulting firms and staffing arms of real employers are fine.

    DO NOT REJECT for anything you cannot see on the card. Missing information is NOT a reason
    to reject. If you are unsure, KEEP the job. A wrongly kept job costs one deep scrape; a
    wrongly rejected job is lost entirely.

    From the survivors, return EXACTLY 15 ids -- the 15 whose titles align best with the
    candidate's background in data science, analytics, machine learning, consulting, research,
    and public policy. Prefer titles that signal early-career or new-graduate hiring.

    Returning fewer than 15 is only acceptable if fewer than 15 cards survive the reject rules
    above. Do not ration the list for quality: a later stage reads the full description of each
    one and scores it strictly. Your budget exists to be spent. If you find yourself returning
    5 or 6, you are being too strict -- go back and include the next-best candidates.

    Jobs: {jobs_str}

    Output ONLY a valid JSON array of the integer "id" values of the jobs you selected.
    Example: [3, 17, 204, 511]
    Maximum 15 ids. No markdown, no commentary, no other fields.
    """

    if len(fresh_jobs) <= 15:
        # Short enough to deep-scrape in full -- no reason to let a model drop any.
        print(f"Only {len(fresh_jobs)} eligible jobs -- skipping the Sifter and deep-scraping all.")
        sifted_jobs = list(fresh_jobs)
    else:
        sifter_response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=sift_prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        try:
            clean_json = sifter_response.text.replace("```json", "").replace("```", "").strip()
            chosen_ids = json.loads(clean_json)
            by_id = {j["id"]: j for j in fresh_jobs}
            sifted_jobs = [by_id[i] for i in chosen_ids if isinstance(i, int) and i in by_id]
            dropped = len(chosen_ids) - len(sifted_jobs)
            if dropped:
                print(f"Warning: Sifter returned {dropped} unknown id(s); ignored.")
        except Exception as e:
            print(f"Error parsing Sifter JSON: {e}")
            return

    with open("sifted_jobs.json", "w") as f:
        json.dump(sifted_jobs, f, indent=4)
    print(f"Sifter kept {len(sifted_jobs)} of {len(fresh_jobs)} jobs for deep scraping.")
    for j in sifted_jobs:
        print(f"   -> [{j.get('id')}] {j.get('company','?')} | {j.get('title','?')[:60]}"
              f" | {j.get('location','?')}")
    if len(sifted_jobs) == 0:
        print("!!! Nothing selected for deep scraping. !!!")

    # --- PHASE 5: The Deep Scrape ---
    run_script("deep_scraper.py")

    # --- PHASE 6: THE FINAL GRADER (Holistic Batch Optimization) ---
    print("\n--- PHASE 6: THE FINAL GRADER (WRITING THE PLAYBOOK) ---")
    
    if not os.path.exists("deep_jobs.json"):
        print("No deep scraped data found. Ending pipeline.")
        return

    with open("deep_jobs.json", "r") as f:
        final_targets = json.load(f)

    # LinkedIn prints this on postings that have closed. No point grading them.
    closed = [j for j in final_targets
              if "no longer accepting applications" in (j.get("full_description") or "").lower()]
    if closed:
        for j in closed:
            if j.get("url"):
                mark_job_rejected(j["url"])
        final_targets = [j for j in final_targets if j not in closed]
        print(f"Dropped {len(closed)} closed posting(s) before grading.")

    all_jobs_text = json.dumps(final_targets, indent=2)

    print(f"Batch analyzing {len(final_targets)} descriptions to save API tokens...")

    batch_grade_prompt = f"""
    You are an elite career strategist. 
    
    CANDIDATE BACKGROUND & PREFERENCES:
    {candidate_context}

    Here is a JSON array containing multiple job descriptions, which include their URLs:
    {all_jobs_text}

    TASK:
    For EVERY job in the array, you MUST perform a strict verification before scoring:
    
    STEP 1: THE HOLISTIC ALIGNMENT CHECKLIST
    Mentally answer these questions based strictly on the candidate's context. Do not invent constraints or assume exceptions:
    1. Education/Experience Matrix: If the job uses "OR" logic, does the pathway matching the candidate's degree require years of experience they do not currently possess? (Check rubric for equivalence).
    2. Technical Infrastructure: Does the job's actual engineering stack fundamentally mismatch the candidate's proven technical background?
    3. Stated Preferences & Rubric: Does the job violate ANY explicit dealbreaker mentioned in the candidate's custom rubric?
    4. Temporary Role: Is this role an "Intern", "Internship", or temporary summer program? If it is, you MUST answer YES. 
    5. Predatory Business Model: Is this job posted by a third-party staffing agency, resume farm, or pay-to-play bootcamp (e.g., SynergisticIT, Revature, FDM Group), or a job aggregator reposting other companies' roles (e.g., Jobright, Lensa, Jobs via Dice)? (NOTE: Do NOT flag premier management consulting firms or legitimate corporate early-career rotational training programs).
    6. The "Years of Experience" Trap: Does the job explicitly mandate 1, 2, or more years of full-time professional experience? If yes, you MUST answer YES. You are strictly forbidden from hallucinating a "New Grad" label to bypass this requirement.
    7. The Graduation Timeline Trap (The Kill Switch): Does the job explicitly target students graduating in late 2027 (e.g., December 2027) or Spring 2028? The candidate is a Spring 2027 graduate. If the job targets a later graduation cohort, you MUST answer YES.
    8. The Hard Requirement Trap: Does the job state any non-negotiable qualification the candidate
       does not hold? This includes, but is not limited to:
         * Fluency in a language the candidate does not speak. The candidate speaks ENGLISH,
           ARABIC, and FRENCH only. A requirement for any other language is an automatic YES.
         * A security clearance, professional licence, or certification the candidate lacks.
         * A degree field or level the candidate does not have.
       Treat "must", "required", "fluent level", and similar phrasing as non-negotiable.
    9. The Location Trap: The candidate is based in BOSTON and CANNOT RELOCATE. Answer YES if the
       role's work location is outside commuting distance of Boston, Massachusetts, and the posting
       does not explicitly offer fully remote work. Roles listing Boston among several offices are
       acceptable. If the posting implies a non-US work location (for example by requiring local
       language fluency or local work authorisation), answer YES.
    
    STEP 2: SCORING
    * If the answer to ANY of the Alignment questions (1 through 9) is YES, the Match Score is automatically 0/100.
    * Only if ALL Alignment answers are NO, calculate a true Match Score out of 100 based on holistic skill and narrative alignment.

    STEP 3: STRICT FILTERING & FORMATTING
    1. THE EXCLUSION RULE: You MUST silently omit any job that scores below 85. Do NOT print jobs with a score of 0.
    2. THE SORTING RULE: You MUST sort the surviving jobs in descending order by Match Score.
    
    Format EVERY surviving job EXACTLY like the template below. 
    CRITICAL LINK INSTRUCTION: You MUST wrap the Job Title in square brackets `[]` and
    immediately follow it with parentheses `()` containing the token JOB_URL_<id>, where <id>
    is the job's own integer "id" field from the JSON. This creates a valid Markdown link once
    the system substitutes the real URL. Do NOT write the URL yourself, and do NOT omit the
    brackets or parentheses -- either mistake breaks the report.
    Correct:   ### [Junior Data Analyst](JOB_URL_42)
    Wrong:     ### Junior Data Analyst (JOB_URL_42)
    Wrong:     ### [Junior Data Analyst](https://www.linkedin.com/...)
    
    ### [EXACT JOB TITLE FROM JSON](JOB_URL_<id>)
    
    * **Company:** 🏢 INSERT_COMPANY_NAME
    * **Match Score:** 🎯 [Score]/100  
    * **Category:** 📂 [Category]  
    * **Deadline/Timeline:** ⏳ [Extract the explicit deadline date. If none is listed, write "Rolling / ASAP. Apply immediately."]
    
    **🟢 PROS (Alignment):**
    * [List 1-2 reasons why this job aligns with the candidate's skills or targets]
    
    **🔴 POTENTIAL HURDLES:**
    * [List any minor missing skills or things the candidate should prepare to defend in an interview]
    
    **⚖️ THE VERDICT:**
    * [One sentence explaining why this is a high-probability match]
    
    ---
    
    If NO jobs score 85 or higher, do not print any jobs. Output exactly: "No high-scoring matches found in this batch. Keep refining the search queries!"
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=batch_grade_prompt,
        config=types.GenerateContentConfig(temperature=0.3)
    )
    
    report_text = response.text.strip()

    # Swap JOB_URL_<id> tokens for the real URLs. The model never handles a URL, so a
    # title can no longer be paired with another job's link.
    passed_ids = set()
    for job in final_targets:
        jid = job.get("id")
        if jid is None:
            continue
        token = f"JOB_URL_{jid}"
        if token in report_text:
            report_text = report_text.replace(token, job.get("url", ""))
            passed_ids.add(jid)

    leftover = re.findall(r"JOB_URL_\d+", report_text)
    if leftover:
        print(f"Warning: {len(leftover)} unresolved link token(s) in report: {set(leftover)}")

    with open("FINAL_STRATEGY.md", "w") as f:
        f.write("# 🎯 Weekly AI Job Strategy: High-Probability Matches\n\n")
        f.write(report_text)

    # Record outcomes: anything that made the report gets packaged, the rest
    # goes on a COOLDOWN_DAYS timer rather than a permanent blacklist.
    passed = rejected = 0
    for job in final_targets:
        url = job.get("url")
        if not url:
            continue
        if job.get("id") in passed_ids:
            mark_job_packaged(url)
            passed += 1
        else:
            mark_job_rejected(url)
            rejected += 1
    print(f"Grader outcome: {passed} passed, {rejected} scored below threshold "
          f"(re-checked in 21 days).")

    # --- PHASE 7: AUTO-FULFILLMENT ENGINE ---
    # Generates tailored bullet points and cover letters right after the playbook is compiled
    run_script("auto_fulfiller.py")

    print("\n=======================================================")
    print(" PIPELINE COMPLETE! Report generated in FINAL_STRATEGY.md ")
    print("=======================================================")
    
    if os.environ.get("EMAIL_USER") and os.environ.get("EMAIL_PASS"):
        try:
            from notifier import send_strategy_report
            send_strategy_report(os.environ.get("EMAIL_USER"))
        except ImportError:
            print("Notice: notifier.py not found. Skipping email dispatch.")

if __name__ == "__main__":
    main()