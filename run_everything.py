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

def classify_and_load_rubric(job_title, job_description, model):
    """
    Acts as a triage agent. Classifies the job and loads the appropriate grading rubric.
    """
    classifier_prompt = f"""
    You are a career triage agent. Look at this job:
    Title: {job_title}
    Description: {job_description}

    Classify this job into EXACTLY ONE of these three categories based on its primary focus:
    1. LEGAL_POLICY (Focuses on compliance, ethics, geopolitical analysis, or public policy)
    2. TECHNICAL_DATA (Focuses on coding, machine learning, data engineering, or heavy analytics)
    3. GENERAL (Standard corporate, consulting, or administrative roles that don't fit the above)

    Respond with ONLY the category name. Do not include any other text.
    """

    # 1. Ask Gemini to classify the job
    response = model.generate_content(classifier_prompt)
    category = response.text.strip().upper()

    # 2. Route to the correct rubric file
    if "LEGAL" in category:
        file_path = "rubrics/legal_policy.txt"
        print(f" -> Triage: Routed '{job_title}' to Legal/Policy Rubric.")
    elif "TECHNICAL" in category:
        file_path = "rubrics/technical_data.txt"
        print(f" -> Triage: Routed '{job_title}' to Technical/Data Rubric.")
    else:
        file_path = "rubrics/general.txt"
        print(f" -> Triage: Routed '{job_title}' to General Rubric.")

    # 3. Load and return the rubric text
    with open(file_path, "r") as f:
        rubric_text = f.read()

    return rubric_text, category

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

    if os.path.exists("preferences.txt"):
        with open("preferences.txt", "r") as f:
            candidate_context += "\n\n--- EXPLICIT CANDIDATE PREFERENCES & TIMELINES ---\n"
            candidate_context += f.read()

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
    
    1. The Education/Experience Matrix Check: Pay strict attention to "OR" logic in qualifications (e.g., "Master's OR Bachelor's + 3 years"). You must isolate the specific pathway that matches the candidate's highest degree. Mathematically calculate the candidate's exact years of full-time professional experience from their resume, and compare it against the job's minimum requirement for that pathway. 
    STRICT BINDING RULE: If (Candidate's Actual Years) is less than (Job's Required Years), the Match Score is automatically 0/100. Exceptional narrative alignment, matching technical tools, or project overlap does NOT override a mathematical deficit in required years. Act like a heartless corporate bureaucrat—if they do not have the raw numbers, it is an immediate failure.
    2. The Technical Infrastructure & Deployment Check: Do not be misled by broad, shared industry concepts. Evaluate the job's actual day-to-day deployment target and underlying engineering stack. If the role operates in a fundamentally different technical environment, physical infrastructure, or software architecture than what the candidate has proven on their resume, reject it. A shared conceptual buzzword does not equal a shared technical reality.
    3. The Stated Preference Check: Cross-reference the job against the candidate's explicit preferences. If the job violates a stated dealbreaker (visa policies, location, timeline, industry aversions, or travel requirements), reject it immediately. Do NOT invent constraints the candidate has not stated.
    4. The Internship/Temporary Veto: The job MUST be a permanent post-graduation role. Reject any "Intern", "Internship", "Co-op", or summer program.

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
    1. Education/Experience Matrix: If the job uses "OR" logic for degrees/experience, does the specific pathway matching the candidate's degree require years of experience they do not currently possess?
    2. Technical Infrastructure: Looking past broad conceptual buzzwords, does the job's actual underlying engineering stack, physical deployment target, or software architecture fundamentally mismatch the candidate's proven technical background?
    3. Stated Preferences: Does the job violate ANY explicit dealbreaker (visa policies, location, timeline, industry aversions, travel) mentioned in the candidate's preferences?
    4. Temporary Role: Is this role an "Internship", "Co-op", or temporary summer program rather than a permanent post-graduate role?
    
    STEP 2: SCORING
    * If the answer to ANY of the Alignment questions is YES, the Match Score is automatically 0/100. Do not write a gameplan.
    * Only if ALL Alignment answers are NO, calculate a true Match Score out of 100 based on holistic skill and narrative alignment.

    STEP 3: STRICT FILTERING & FORMATTING
    1. THE EXCLUSION RULE: You MUST silently omit any job that scores below 85. Do NOT print jobs with a score of 0. Do NOT show your work for rejected jobs.
    2. THE SORTING RULE: You MUST sort the surviving jobs in descending order by Match Score (e.g., 98/100 at the top, 85/100 at the bottom).
    
    Return a Markdown report containing ONLY the surviving jobs that scored 85 or higher. 
    You MUST format the job title as a clickable Markdown link using the exact URL from the JSON data. Do NOT add spaces between the brackets and parentheses. 
    
    Format each winner exactly like this:
    
    ## [INSERT_JOB_TITLE](INSERT_ACTUAL_URL_HERE)
    
    **Company:** 🏢 INSERT_COMPANY_NAME
    **Match Score:** 🎯 [Score]/100  
    **Category:** 📂 [Category]  
    
    **Gameplan:**
    * [Step 1]
    * [Step 2]
    * [Step 3]
    
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
    
    from notifier import send_strategy_report
    send_strategy_report("ysouayah@bu.edu")

if __name__ == "__main__":
    main()