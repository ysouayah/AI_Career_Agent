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
    #export GEMINI_API_KEY = "Insert Key Here" <-- write in your terminal. I did not hard encode a key.
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
    
    # Make sure the database exists
    init_db()
    
    raw_jobs = []
    for file in ["handshake_jobs.json", "linkedin_jobs.json", "indeed_jobs.json"]:
        if os.path.exists(file):
            with open(file, "r") as f:
                raw_jobs.extend(json.load(f))
                
    print(f"Total raw jobs scraped across all platforms: {len(raw_jobs)}")
    
    # Filter out jobs we've already seen
    fresh_jobs = []
    for job in raw_jobs:
        if not is_job_seen(job['url']):
            fresh_jobs.append(job)
            # Mark it as seen so we don't process it next week
            mark_job_seen(job['url'])
            
    print(f"Total FRESH, unseen jobs for the AI to evaluate: {len(fresh_jobs)}")
    
    if len(fresh_jobs) == 0:
        print("No new jobs found this week. Sleeping until next run.")
        return # Stops the script early so we don't waste AI tokens!

    jobs_str = json.dumps(fresh_jobs, indent=2)

    # Rebuild candidate context
    candidate_context = "--- MASTER RESUME ---\n"
    candidate_context += extract_resume_text("Souayah_Youssef_Master_Resume.docx-5.pdf")
    if os.path.exists("transcript.pdf"):
        candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n"
        candidate_context += extract_resume_text("transcript.pdf")
    # =====================================================================
# IMPORTANT: API KEY SETUP
# To run this agent locally, you must set your Gemini API key in your terminal first.
# Run this command in your terminal before executing the script:
# Mac/Linux: export GEMINI_API_KEY="your_api_key_here"
# Windows: set GEMINI_API_KEY="your_api_key_here"
# =====================================================================
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"temperature": 0.3})

    # --- PHASE 4: The Sifter (Finding the Top 15) ---
    print("\n--- PHASE 4: THE SIFTER (SELECTING TARGETS FOR DEEP DIVE) ---")
    sift_prompt = f"""
    You are an elite recruiter. Here is your client's profile:
    {candidate_context}

    Here is a massive list of raw job preview cards:
    {jobs_str}

    Your task:
    Review the preview cards. Select the Top 15 roles that look the MOST promising for this candidate's dual Political Science/Data Science background. 
    Output ONLY a valid JSON array of the original JSON objects for the 15 jobs you selected. Do not add markdown or text. Just the raw JSON array.
    """
    
    sifter_response = model.generate_content(sift_prompt)
    
    try:
        clean_json = sifter_response.text.replace("```json", "").replace("```", "").strip()
        sifted_jobs = json.loads(clean_json)
        with open("sifted_jobs.json", "w") as f:
            json.dump(sifted_jobs, f, indent=4)
        print("Sifter successfully selected the Top 15 targets.")
    except Exception as e:
        print("Error parsing Sifter JSON. The AI might have included text. Ending pipeline.")
        return

    # --- PHASE 5: The Deep Scrape ---
    run_script("deep_scraper.py")

    # --- PHASE 6: The Final Grader ---
    print("\n--- PHASE 6: THE FINAL GRADER (WRITING THE PLAYBOOK) ---")
    with open("deep_jobs.json", "r") as f:
        deep_jobs_data = json.dumps(json.load(f), indent=2)

    grade_prompt = f"""
    You are an elite career strategist. Here is your client's profile:
    {candidate_context}

    Here is the FULL TEXT of the job descriptions for our top targets:
    {deep_jobs_data}

    Your task:
    1. Read every full job description and compare it to the client's profile.
    2. Calculate a Match Score out of 100 based STRICTLY on this rubric:
       - BASELINE TECHNICAL (30 Pts): Explicitly requires data analysis, Python, APIs, web scraping, or AI.
       - BASELINE DOMAIN (30 Pts): Operates in a policy, government, legal, geopolitical, or ethical sector.
       - EXPERIENCE MATCH (20 Pts): Is an internship/entry-level role (0-2 years). Subtract 10 pts for every year required over 2.
       - UNICORN MULTIPLIERS (20 Pts): Award 5 pts for EACH of the following explicit mentions:
            1. Trilingual skills / French / Arabic / MENA regions.
            2. Algorithmic bias / AI ethics / Code auditing.
            3. Public speaking / Debate / Presenting to non-technical stakeholders.
            4. Web automation / Playwright / Data pipelines.
            
    3. Filter the list and select EVERY role where the calculated score is 90/100 or higher.
    4. For ALL selected jobs, provide:
       - The Job Title, Company, and Platform.
       - Match Score (e.g., 95/100).
       - The "Gameplay": A highly tactical 3-step plan to secure the interview. Do NOT include a breakdown or reasoning for the score.

    Output this as a clean text report formatted beautifully using markdown. If no jobs score 90 or higher, inform the client and suggest what skills were missing from the search.
    """

    print("Analyzing full descriptions and grading against the Unicorn Rubric...")
    final_response = model.generate_content(grade_prompt)

    with open("FINAL_STRATEGY.md", "w") as f:
        f.write(final_response.text)

    print("\n=======================================================")
    print(" PIPELINE COMPLETE! ")
    print(" Open 'FINAL_STRATEGY.md' to see your True Unicorn matches. ")
    print("=======================================================")
    
    # Send the email report
    from notifier import send_strategy_report
    send_strategy_report("ysouayah@bu.edu")

if __name__ == "__main__":
    main()
