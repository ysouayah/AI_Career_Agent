from google import genai
from google.genai import types
import os
import json
import sys
import tomllib 
from resume_parser import extract_resume_text
import time

def main():
    print("\n[Brainstormer] >> Analyzing candidate profile to determine search targets...")

    # Load Streamlit secrets for standalone testing
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
            for key, value in secrets.items():
                os.environ[key] = str(value)

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)

    # 1. Gather the Context
    resume_text = ""
    if os.path.exists("resume.pdf"):
        resume_text = extract_resume_text("resume.pdf")
    
    # 2. Extract Permanent Preferences
    preferences = ""
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r") as f:
            preferences = json.dumps(json.load(f), indent=2)

    # 3. Configure the New LLM Client
    client = genai.Client()

    # 4. The Extraction Prompt
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

    # 5. Generate and Save the Targets (With 503 Retry Logic)
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            
            clean_json = response.text.replace("```json", "").replace("```", "").strip()
            targets = json.loads(clean_json)
            
            if not targets.get("titles") or len(targets["titles"]) == 0:
                raise ValueError("AI response structure is missing valid job titles.")
                
            with open("search_targets.json", "w") as f:
                json.dump(targets, f, indent=4)
                
            print(f"[Brainstormer] >> Success! Targets locked: {targets['titles']} in {targets['locations']}")
            break # Exit the retry loop on success
            
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                wait_time = (attempt + 1) * 15 # Wait 15s, then 30s, then 45s...
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