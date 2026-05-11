import os
import json
import google.generativeai as genai
from resume_parser import extract_resume_text

# --- 1. THE CONTEXT PIPELINE (Your Code!) ---
# Make sure your actual resume PDF name matches here
candidate_context = "--- MASTER RESUME ---\n"
candidate_context += extract_resume_text("YSouayah_MasterResume.pdf")
transcript_file = "Transcript_BU001_U86211426-4.pdf"

if os.path.exists(transcript_file):
    print("Optional transcript detected! Adding to AI context...")
    candidate_context += "\n\n--- ACADEMIC TRANSCRIPT ---\n"
    candidate_context += extract_resume_text(transcript_file)
else:
    print("No transcript found. Proceeding with Resume only.")

# --- 2. THE AI ENGINE ---
# Make sure your API key is set in your terminal environment variables!
# export GEMINI_API_KEY="your_api_key_here"
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def brainstorm_jobs(context_text):
    print("\nThinking... Asking Gemini to brainstorm niche roles based on your profile...")
    
    # We use Flash here because it's fast and perfect for text analysis
    model = genai.GenerativeModel('gemini-2.5-flash') 
    
    prompt = f"""
    You are an elite technical and political recruiter. Review the following candidate profile:
    {context_text}
    
    Based strictly on their specific skills, experience, and education, generate a list of 5 to 8 highly specific job titles they have the best chance of landing. 
    Do not just say "Data Analyst". Look for cross-sections of their skills (e.g., Public Policy Analyst, Legal Tech Researcher, Elections Data Coordinator).
    
    Return ONLY a valid JSON array of strings. Do not include markdown formatting, code blocks, or explanations. 
    Example: ["Title 1", "Title 2", "Title 3"]
    """
    
    response = model.generate_content(prompt)
    
    # --- 3. PARSE AND SAVE ---
    try:
        # Clean up the response just in case the AI added markdown blocks
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        job_titles = json.loads(clean_text)
        
        print("\nSuccess! Here are your high-probability job targets:")
        for i, title in enumerate(job_titles, 1):
            print(f"{i}. {title}")
            
        # We save this array to a JSON file so our scrapers can loop through it later
        with open("target_queries.json", "w") as f:
            json.dump(job_titles, f, indent=4)
            
        print("\nSaved to 'target_queries.json'. Our scrapers are ready to hunt.")
        
    except Exception as e:
        print(f"\nFailed to parse AI response. Error: {e}")
        print("Raw output was:")
        print(response.text)

if __name__ == "__main__":
    # Ensure the API key is actually set before running
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not found.")
        print("Run this in your terminal first: export GEMINI_API_KEY='your_key'")
    else:
        brainstorm_jobs(candidate_context)