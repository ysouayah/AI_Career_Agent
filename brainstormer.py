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

    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
            for key, value in secrets.items():
                os.environ[key] = str(value)

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)

    resume_text = ""
    if os.path.exists("resume.pdf"):
        resume_text = extract_resume_text("resume.pdf")
    
    preferences = ""
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r") as f:
            preferences = json.dumps(json.load(f), indent=2)

    client = genai.Client()

    prompt = f"""
    Analyze the following candidate profile.
    Resume: {resume_text}
    Preferences: {preferences}
    
    Return a strict JSON object with two keys to guide our job scraper:
    "titles": [A list of 3 to 5 highly relevant job titles to search for]
    "locations": [A list of 1 to 3 relevant locations, e.g., "Boston, MA", "Remote"]
    """

    max_retries = 5
    for attempt in range(max_retries):
        try:
            # Forcing native JSON mode at the API level
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
            
            # Since it's native JSON, we can load it directly without text replacement hacks
            targets = json.loads(response.text.strip())
            
            if not targets.get("titles") or len(targets["titles"]) == 0:
                raise ValueError("AI response structure is missing valid job titles.")
                
            with open("search_targets.json", "w") as f:
                json.dump(targets, f, indent=4)
                
            print(f"[Brainstormer] >> Success! Targets locked: {targets['titles']} in {targets['locations']}")
            break 
            
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                wait_time = (attempt + 1) * 15 
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