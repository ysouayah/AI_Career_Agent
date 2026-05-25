import os
import json
import google.generativeai as genai
from resume_parser import extract_resume_text

def main():
    print("\n[brainstormer.py] >> Initiating sequence...")
    
    # 1. Grab the API Key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found. Brainstormer cannot run.")
        return
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"temperature": 0.4})

    # 2. Read the Candidate Context FIRST
    candidate_context = "--- MASTER RESUME ---\n"
    if os.path.exists("resume.pdf"):
        candidate_context += extract_resume_text("resume.pdf")
    else:
        print("Warning: resume.pdf not found. Generating generic queries.")

    if os.path.exists("transcript.pdf"):
        candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n"
        candidate_context += extract_resume_text("transcript.pdf")

    # 3. Ask Gemini to generate the absolute best search queries based ON the resume
    query_prompt = f"""
    You are an elite technical recruiter. Analyze this candidate's profile and preferences:
    {candidate_context}

    YOUR MISSION: 
    1. Dynamically deduce the candidate's core industry, strongest skills, and career trajectory based ONLY on the provided text.
    2. Generate exactly 12 highly targeted job search queries for job boards (like LinkedIn or Handshake) tailored SPECIFICALLY to this candidate's reality.

    CRITICAL SOURCING RULES (THE FUNNEL FIX):
    1. THE FULL-TIME MANDATE: The candidate is looking exclusively for FULL-TIME, POST-GRADUATION roles. You MUST append strict early-career modifiers for full-time work (e.g., "New Grad", "Entry Level", "Rotational Program", "Associate"). 
    2. THE INTERNSHIP BAN: You MUST NOT generate any query for internships or co-ops. You should append "-intern -internship" to the end of your generated queries to force job boards to exclude temporary student roles (e.g., "New Grad Data Scientist -intern -internship").
    3. THE GENERIC BAN: Never output naked titles (e.g., "Data Scientist", "Analyst", "Engineer"). Anchor the title to their specific seniority and their unique niche.
    4. NO ASSUMPTIONS: Do not assume any specific industry (like AI or Public Policy) unless the candidate's resume or preferences explicitly point to it.

    Output ONLY a valid JSON array of 12 strings. Do not include markdown formatting or any other text.
    """

    print("Analyzing candidate profile to generate highly targeted search queries...")
    response = model.generate_content(query_prompt)

    # 4. Save the queries for the extractors to use
    try:
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        target_queries = json.loads(clean_json)
        
        with open("target_queries.json", "w") as f:
            json.dump(target_queries, f, indent=4)
            
        print(f"Success! Generated tailored queries: {target_queries}")
    except Exception as e:
        print(f"Error parsing Brainstormer JSON: {e}")
        # Fallback queries just in case the AI hallucinates formatting
        fallback = ["Data Analyst", "Policy Analyst", "Technical Project Manager"]
        with open("target_queries.json", "w") as f:
            json.dump(fallback, f)

if __name__ == "__main__":
    main()