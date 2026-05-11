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

    # Rebuild candidate context (Generalized filename for GitHub)
    candidate_context = "--- MASTER RESUME ---\n"
    candidate_context += extract_resume_text("Souayah_Youssef_Master_Resume.docx-5.pdf")
    if os.path.exists("transcript.pdf"):
        candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n"
        candidate_context += extract_resume_text("transcript.pdf")

    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"temperature": 0.3})

    # --- PHASE 4: The Sifter ---
    print("\n--- PHASE 4: THE SIFTER (SELECTING TARGETS) ---")
    sift_prompt = f"""
    You are an elite recruiter. Here is your client's profile:
    {candidate_context}

    Review these job cards and select the Top 15 roles.
    Jobs: {jobs_str}

    Output ONLY a valid JSON array of the objects for the 15 jobs selected.
    """
    
    sifter_response = model.generate_content(sift_prompt)
    
    try:
        clean_json = sifter_response.text.replace("```json", "").replace("```", "").strip()
        sifted_jobs = json.loads(clean_json)
        with open("sifted_jobs.json", "w") as f:
            json.dump(sifted_jobs, f, indent=4)
        print("Sifter successfully selected the Top 15 targets.")
    except Exception as e:
        print(f"Error parsing Sifter JSON: {e}")
        return

    # --- PHASE 5: The Deep Scrape ---
    run_script("deep_scraper.py")

    # --- PHASE 6: THE FINAL GRADER ---
    print("\n--- PHASE 6: THE FINAL GRADER (WRITING THE PLAYBOOK) ---")
    
    if not os.path.exists("deep_jobs.json"):
        print("No deep scraped data found. Ending pipeline.")
        return

    with open("deep_jobs.json", "r") as f:
        final_targets = json.load(f)

    full_report_content = "# 🎯 Weekly AI Job Strategy: High-Probability Matches\n\n"
    high_match_found = False

    print(f"Analyzing {len(final_targets)} descriptions against dynamic rubrics...")

    for job in final_targets:
        title = job.get("title", "Unknown Title")
        company = job.get("company", "Unknown Company")
        desc = job.get("description", "")

        # 1. Triage: Pick the right rubric
        current_rubric, category_label = classify_and_load_rubric(title, desc, model)

        # 2. Grade
        grade_prompt = f"""
        You are an elite career strategist. 
        CANDIDATE BACKGROUND: {candidate_context}
        RUBRIC ({category_label}): {current_rubric}

        JOB: {title} at {company}
        DESCRIPTION: {desc}

        TASK:
        1. Calculate a Match Score out of 100 based on the rubric.
        2. If score >= 85, provide a 3-step 'Gameplan'.
        3. If score < 85, respond ONLY with 'SKIP'.
        
        OUTPUT FORMAT (If score >= 85):
        ## {title} | {company}
        **Match Score:** [Score]/100
        **Category:** {category_label}
        **Gameplan:**
        - [Step 1]
        - [Step 2]
        - [Step 3]
        ---
        """

        response = model.generate_content(grade_prompt)
        result_text = response.text.strip()

        if "SKIP" not in result_text.upper():
            full_report_content += result_text + "\n"
            high_match_found = True

    if not high_match_found:
        full_report_content += "No high-scoring matches found in this batch."

    with open("FINAL_STRATEGY.md", "w") as f:
        f.write(full_report_content)

    print("\n=======================================================")
    print(" PIPELINE COMPLETE! Report generated in FINAL_STRATEGY.md ")
    print("=======================================================")
    
    from notifier import send_strategy_report
    send_strategy_report("ysouayah@bu.edu")

if __name__ == "__main__":
    main()