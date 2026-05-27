import subprocess
import json
import os
import google.generativeai as genai
from resume_parser import extract_resume_text

def run_script(script_name):
    print(f"\n[{script_name}] >> Initiating sequence...")
    try:
        subprocess.run(["python3", script_name], check=True)
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
    for job in raw_jobs:
        if not is_job_seen(job['url']):
            fresh_jobs.append(job)
            mark_job_seen(job['url'])
            
    print(f"Total FRESH jobs for evaluation: {len(fresh_jobs)}")
    
    if len(fresh_jobs) == 0:
        print("No new jobs found this week. Sleeping until next run.")
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
    if os.path.exists("preferences.txt"):
        with open("preferences.txt", "r") as f:
            prefs_content = f.read().strip()
        
        if prefs_content:
            candidate_context += prefs_content
        else:
            candidate_context += "Evaluate jobs based on general professional fit, standard industry entry requirements, and alignment with the provided resume skills."
    else:
        candidate_context += "Evaluate jobs based on general professional fit, standard industry entry requirements, and alignment with the provided resume skills."

    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"temperature": 0.3})

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
    
    sifter_response = model.generate_content(sift_prompt)
    
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
    4. Temporary Role: Is this role an "Internship" or temporary program? (Check rubric for contractor overrides).
    
    STEP 2: SCORING
    * If the answer to ANY of the Alignment questions is YES, the Match Score is automatically 0/100.
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
    
    **🟢 PROS (Alignment):**
    * [List 1-2 reasons why this job aligns with the candidate's skills or targets]
    
    **🔴 POTENTIAL HURDLES:**
    * [List any minor missing skills or things the candidate should prepare to defend in an interview]
    
    **⚖️ THE VERDICT:**
    * [One sentence explaining why this is a high-probability match]
    
    ---
    
    If NO jobs score 85 or higher, do not print any jobs. Output exactly: "No high-scoring matches found in this batch. Keep refining the search queries!"
    """

    response = model.generate_content(batch_grade_prompt)
    
    with open("FINAL_STRATEGY.md", "w") as f:
        f.write("# 🎯 Weekly AI Job Strategy: High-Probability Matches\n\n")
        f.write(response.text.strip())

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