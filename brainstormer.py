import google.generativeai as genai
import os
import json
import sys
from resume_parser import extract_resume_text

def main():
    print("\n[Brainstormer] >> Analyzing candidate profile to determine search targets...")

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)

    # 1. Gather the Context
    resume_text = ""
    if os.path.exists("resume.pdf"):
        resume_text = extract_resume_text("resume.pdf")
    
    preferences = ""
    if os.path.exists("preferences.txt"):
        with open("preferences.txt", "r") as f:
            preferences = f.read()

    # 2. Configure the LLM
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"temperature": 0.2})

    # 3. The Extraction Prompt
    prompt = f"""
    You are an elite AI Career Agent. Read this candidate's resume and explicit preferences.
    
    --- RESUME ---
    {resume_text}
    
    --- PREFERENCES & DEALBREAKERS ---
    {preferences}
    
    TASK:
    Based on their background and their explicit requests, determine the best job search parameters to feed into an automated web scraper. 
    
    1. TITLES: Generate an array of 3 to 4 highly relevant job titles tailored to this specific user.
    2. LOCATIONS: Extract the geographical locations they want to work in from their Preferences (e.g., "Boston, MA", "Remote", "New York, NY"). If they did not specify a location, default to "United States".

    Output ONLY a valid JSON object in this exact format. Do not include markdown formatting, backticks, or any other text.
    {{
        "titles": ["Title 1", "Title 2", "Title 3"],
        "locations": ["Location 1", "Location 2"]
    }}
    """

    # 4. Generate and Save the Targets
    try:
        response = model.generate_content(prompt)
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        targets = json.loads(clean_json)
        
        # Guard clause to ensure the AI actually returned structured titles
        if not targets.get("titles") or len(targets["titles"]) == 0:
            raise ValueError("AI response structure is missing valid job titles.")
            
        with open("search_targets.json", "w") as f:
            json.dump(targets, f, indent=4)
            
        print(f"[Brainstormer] >> Success! Targets locked: {targets['titles']} in {targets['locations']}")
        
    except Exception as e:
        print(f"\n❌ [Brainstormer] FATAL ERROR: Failed to automatically generate search targets.")
        print(f"Details: {e}")
        print("Pipeline halted to prevent unconfigured scraping queries.\n")
        sys.exit(1)

if __name__ == "__main__":
    main()