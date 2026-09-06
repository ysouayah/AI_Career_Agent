import subprocess
import json
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
    from database_manager import init_db, is_job_seen, mark_job_seen
    
    init_db()
    
    raw_jobs = []
    for file in ["handshake_jobs.json", "linkedin_jobs.json", "indeed_jobs.json"]:
        if os.path.exists(file):
            with open(file, "r") as f:
                raw_jobs.extend(json.load(f))
                
    print(f"Total raw jobs scraped: {len(raw_jobs)}")
    
    fresh_jobs = []
    seen_signatures = set() # Tracks Company + Title combos to kill ATS spam
    
    for job in raw_jobs:
        # Create a unique footprint for the job ignoring the URL
        signature = f"{job.get('company', 'Unknown')}_{job.get('title', 'Unknown')}".lower()
        
        # Only process if the URL is new AND the Company+Title combo hasn't been seen today
        if not is_job_seen(job['url']) and signature not in seen_signatures:
            fresh_jobs.append(job)
            mark_job_seen(job['url'])
            seen_signatures.add(signature)
            
    print(f"Total FRESH jobs for evaluation: {len(fresh_jobs)}")
    
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

    jobs_str = json.dumps(fresh_jobs, indent=2)

    # --- DYNAMIC CONTEXT BUILDING ---
    candidate_context = "--- MASTER RESUME ---\n"
    if os.path.exists("resume.pdf"):
        candidate_context += extract_resume_text("resume.pdf")
    else:
        print("Warning: resume.pdf not found. Proceeding with limited context.")

    if os.path.exists("transcript.pdf"):
        candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n"
        candidate_context += extract_resume_text("transcript.pdf")

    candidate_context += "\n\n--- EXPLICIT CANDIDATE PREFERENCES & GRADING RUBRIC ---\n"
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r") as f:
            config = json.load(f)
        
        candidate_context += f"""
        1. THE DUAL-TIMELINE RULE: Evaluate jobs against two strictly acceptable pathways. If a job fits EITHER pathway, it passes.
        - Pathway A ({config['target_timelines']['pathway_a']['type']}): Target window is {config['target_timelines']['pathway_a']['target_window']}.
        - Pathway B ({config['target_timelines']['pathway_b']['type']}): Only accept full-time roles explicitly mentioning a cohort target or graduation marker like {', '.join(config['target_timelines']['pathway_b']['cohort_keywords'])}.
        
        2. THE TECHNICAL & DOMAIN ALIGNMENT: 
        - Prioritize engineering stacks utilizing: {', '.join(config['industry_rubric']['preferred_tech_stack'])}.
        - Look for intersections between {', '.join(config['industry_rubric']['primary_focus'])} and core analytical work in {', '.join(config['industry_rubric']['secondary_interdisciplinary_focus'])}.
        
        3. THE STANDARD REQ VETO: 
        - Active Immediate-Hire Rejection: {config['hard_vetos']['reject_standard_immediate_hire_requisitions']}. Instantly reject any standard corporate job posting that lacks a future cohort target, even if labeled entry-level.
        
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
    sift_prompt = f"""
    You are an elite recruiter. Here is your client's profile and explicit preferences:
    {candidate_context}

    Review these job cards. You must act as a strict but highly nuanced HR filter. 
    
    THE HOLISTIC ALIGNMENT PROTOCOL:
    Before selecting a job, you must perform a nuanced, holistic evaluation of the candidate's application materials against the true nature of the job. If the job fails any of these alignment checks, you MUST reject it:
    
    1. The Education/Experience Matrix Check: Pay strict attention to "OR" logic in qualifications. You must isolate the specific pathway that matches the candidate's highest degree. Mathematically calculate the candidate's exact years of full-time professional experience from their resume, and compare it against the job's minimum requirement for that pathway. 
    STRICT BINDING RULE: If (Candidate's Actual Years) is less than (Job's Required Years), the Match Score is automatically 0/100. Exceptional narrative alignment does NOT override a mathematical deficit in required years, unless explicitly overridden by the candidate's preferences.
    2. The Technical Infrastructure & Deployment Check: Evaluate the job's actual day-to-day deployment target and underlying engineering stack. If the role operates in a fundamentally different technical environment than what the candidate has proven on their resume, reject it.
    3. The Stated Preference Check: Cross-reference the job against the candidate's explicit preferences and custom rubric constraints. If the job violates a stated dealbreaker, reject it immediately. Do NOT invent constraints the candidate has not stated.
    4. The Internship/Temporary Veto: The job MUST be a permanent post-graduation role. Reject any "Intern", "Internship", "Co-op", or summer program unless explicit consulting/contracting overrides are provided in the rubric.

    Jobs: {jobs_str}

    Output ONLY a valid JSON array of the objects for the selected jobs that survived the Protocol (up to 15 max). Do not include markdown or any other text.
    """
    
    sifter_response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=sift_prompt,
        config=types.GenerateContentConfig(temperature=0.3)
    )
    
    try:
        clean_json = sifter_response.text.replace("```json", "").replace("```", "").strip()
        sifted_jobs = json.loads(clean_json)
        with open("sifted_jobs.json", "w") as f:
            json.dump(sifted_jobs, f, indent=4)
        print("Sifter successfully selected the Top targets.")
    except Exception as e:
        print(f"Error parsing Sifter JSON: {e}")
        return

    # --- PHASE 5: The Deep Scrape ---
    run_script("deep_scraper.py")

    # --- PHASE 6: THE FINAL GRADER (Holistic Batch Optimization) ---
    print("\n--- PHASE 6: THE FINAL GRADER (WRITING THE PLAYBOOK) ---")
    
    if not os.path.exists("deep_jobs.json"):
        print("No deep scraped data found. Ending pipeline.")
        return

    with open("deep_jobs.json", "r") as f:
        final_targets = json.load(f)

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
    5. Predatory Business Model: Is this job posted by a third-party staffing agency, resume farm, or pay-to-play bootcamp (e.g., SynergisticIT, Revature, FDM Group)? (NOTE: Do NOT flag premier management consulting firms or legitimate corporate early-career rotational training programs).
    6. The "Years of Experience" Trap: Does the job explicitly mandate 1, 2, or more years of full-time professional experience? If yes, you MUST answer YES. You are strictly forbidden from hallucinating a "New Grad" label to bypass this requirement.
    7. The Graduation Timeline Trap (The Kill Switch): Does the job explicitly target students graduating in late 2027 (e.g., December 2027) or Spring 2028? The candidate is a Spring 2027 graduate. If the job targets a later graduation cohort, you MUST answer YES.
    
    STEP 2: SCORING
    * If the answer to ANY of the Alignment questions (1 through 7) is YES, the Match Score is automatically 0/100.
    * Only if ALL Alignment answers are NO, calculate a true Match Score out of 100 based on holistic skill and narrative alignment.

    STEP 3: STRICT FILTERING & FORMATTING
    1. THE EXCLUSION RULE: You MUST silently omit any job that scores below 85. Do NOT print jobs with a score of 0.
    2. THE SORTING RULE: You MUST sort the surviving jobs in descending order by Match Score.
    
    Format EVERY surviving job EXACTLY like the template below. 
    CRITICAL HYPERLINK INSTRUCTION: You MUST wrap the Job Title in square brackets `[]` and immediately follow it with the job's exact URL from the JSON data in parentheses `()` to create a valid Markdown link. Do not forget the brackets or parentheses!
    
    ### [EXACT JOB TITLE FROM JSON](EXACT URL FROM JSON)
    
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
    
    with open("FINAL_STRATEGY.md", "w") as f:
        f.write("# 🎯 Weekly AI Job Strategy: High-Probability Matches\n\n")
        f.write(response.text.strip())

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