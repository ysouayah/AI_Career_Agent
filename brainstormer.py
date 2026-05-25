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
    You are an elite technical recruiter. Analyze this candidate's profile:
    {candidate_context}

    Based strictly on their unique intersection of skills, generate the 5 most high-probability job search queries we should type into a job board (like Handshake or LinkedIn) to find their perfect role. 
    
    Focus on their specific intersections (e.g., if they have policy and data skills, do not just search "Data Analyst", search "AI Policy Analyst" or "Data Governance").
    
    Output ONLY a valid JSON array of 5 strings. Do not include markdown formatting or any other text.
    Example: ["AI Policy Analyst", "Geopolitical Data Scientist", "Ethical AI Engineer", ...]
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