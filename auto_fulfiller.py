from google import genai
from google.genai import types
import os
import json
import sys
import tomllib
import re
import time
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import shutil
from datetime import datetime
from duckduckgo_search import DDGS

# ==========================================
# 1. TEXT FORMATTING UTILS
# ==========================================
def xml_safe(text):
    """Escapes special characters so ReportLab XML doesn't crash on symbols like & or <."""
    text = text.replace('<b>', '§B§').replace('</b>', '§/B§')
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return text.replace('§B§', '<b>').replace('§/B§', '</b>')

def clean_llm_artifacts(text):
    """Scrubs out leaked AI conversational filler or markdown code block wrappers."""
    lines = text.replace("```markdown", "").replace("```", "").split('\n')
    cleaned = []
    for line in lines:
        if re.match(r'^(PART \d|SECTION \d|\* PART|\*\*PART)', line.strip(), re.IGNORECASE):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned).strip()

# ==========================================
# 2. PDF & CONTENT GENERATORS
# ==========================================
def build_resume_pdf(filename, markdown_resume):
    """Compiles a tight, 0.5-inch margined full ATS Resume PDF."""
    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    
    name_style = ParagraphStyle('ResName', parent=styles['Heading1'], fontSize=18, leading=22, alignment=1, textColor=colors.HexColor("#0F172A"), fontName="Helvetica-Bold")
    contact_style = ParagraphStyle('ResContact', parent=styles['Normal'], fontSize=9, leading=13, alignment=1, textColor=colors.HexColor("#475569"), spaceAfter=12)
    section_style = ParagraphStyle('ResSection', parent=styles['Heading2'], fontSize=11, leading=15, textColor=colors.HexColor("#1E3A8A"), spaceBefore=12, spaceAfter=4, fontName="Helvetica-Bold")
    role_style = ParagraphStyle('ResRole', parent=styles['Normal'], fontSize=10, leading=14, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#0F172A"))
    bullet_style = ParagraphStyle('ResBullet', parent=styles['Normal'], fontSize=9.5, leading=13.5, leftIndent=14, firstLineIndent=-9, spaceAfter=3, textColor=colors.HexColor("#334155"))
    
    story = []
    for line in markdown_resume.split('\n'):
        line = line.strip()
        if not line: continue
        
        while '**' in line:
            line = line.replace('**', '<b>', 1).replace('**', '</b>', 1)
        safe_line = xml_safe(line)
        
        if safe_line.startswith('# '):
            story.append(Paragraph(safe_line[2:], name_style))
        elif safe_line.startswith('## '):
            story.append(Spacer(1, 4))
            story.append(Paragraph(safe_line[3:].upper(), section_style))
        elif safe_line.startswith('### '):
            story.append(Paragraph(safe_line[4:], role_style))
        elif safe_line.startswith('- ') or safe_line.startswith('* '):
            story.append(Paragraph("&bull; " + safe_line[2:], bullet_style))
        elif '|' in safe_line and len(story) <= 2:
            story.append(Paragraph(safe_line, contact_style))
        else:
            story.append(Paragraph(safe_line, bullet_style if len(story) > 3 else contact_style))
            
    doc.build(story)

def build_letter_pdf(filename, company, letter_text):
    """Compiles a classic, formal Cover Letter PDF with a professional letterhead."""
    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54
    )
    styles = getSampleStyleSheet()
    
    name_style = ParagraphStyle('Name', parent=styles['Normal'], fontSize=16, fontName="Helvetica-Bold", textColor=colors.HexColor("#0F172A"), spaceAfter=2)
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], fontSize=10, fontName="Helvetica", textColor=colors.HexColor("#475569"), spaceAfter=18)
    date_style = ParagraphStyle('Date', parent=styles['Normal'], fontSize=10.5, fontName="Helvetica", textColor=colors.HexColor("#1E293B"), spaceAfter=14)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10.5, leading=15.5, textColor=colors.HexColor("#1E293B"), spaceAfter=10, fontName="Helvetica")
    
    story = []
    
    story.append(Paragraph("Youssef Souayah", name_style))
    story.append(Paragraph("ysouayah@bu.edu | linkedin.com/in/ysfsouayah | Boston, MA", contact_style))
    
    current_date = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(current_date, date_style))
    
    story.append(Paragraph(f"Hiring Team<br/>{company}", date_style))
    
    for p in letter_text.split('\n\n'):
        if p.strip():
            clean = p.strip()
            while '**' in clean:
                clean = clean.replace('**', '<b>', 1).replace('**', '</b>', 1)
            story.append(Paragraph(xml_safe(clean).replace('\n', '<br/>'), body_style))
            story.append(Spacer(1, 6))
            
    doc.build(story)

def build_interview_prep_pdf(filename, company, job_title, job_description, client):
    """Generates a targeted interview prep sheet based on the job description."""
    prompt = f"""
    Act as a senior technical recruiter for {company} hiring specifically for the EXACT role of: {job_title}. 
    
    STRICT RULES:
    - Target Job Title: {job_title}. Do NOT invent or prep for a different role.
    - To sound natural, refer to it as "this role" or "this position" in the questions rather than repeating the exact full title 15 times.
    - Base your questions ONLY on the provided job description. 
    - Do not assume responsibilities or technical requirements that are not explicitly stated or implied by the provided job description.

    Based on the following job description, generate 15 highly specific interview questions to prepare the candidate. 
    Include 5 Technical/Hard Skill questions, 5 Behavioral/Cultural questions, and 5 Strategic/Scenario-based questions.
    
    Job Description:
    {job_description}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=prompt
    )
    prep_text = response.text.strip()

    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54
    )
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=16, fontName="Helvetica-Bold", textColor=colors.HexColor("#0F172A"), spaceAfter=15)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10.5, leading=15.5, textColor=colors.HexColor("#1E293B"), spaceAfter=10, fontName="Helvetica")
    
    story = []
    story.append(Paragraph(f"Interview Preparation: {company} - {job_title}", title_style))
    
    for p in prep_text.split('\n\n'):
        if p.strip():
            clean = p.strip()
            while '**' in clean:
                clean = clean.replace('**', '<b>', 1).replace('**', '</b>', 1)
            story.append(Paragraph(xml_safe(clean).replace('\n', '<br/>'), body_style))
            story.append(Spacer(1, 6))
            
    doc.build(story)

def build_company_brief_pdf(filename, company, job_title, job_description, client):
    """Generates a deep-dive company brief to give the candidate an interview edge, grounded in a live web search."""
    
    # 1. Fetch real-world context using DuckDuckGo
    search_context = ""
    try:
        results = DDGS().text(f"{company} company overview mission products", max_results=3)
        if results:
            search_context = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
        else:
            search_context = "No recent web data found. Base analysis strictly on the job description."
    except Exception as e:
        print(f"      [!] Web search failed for {company}: {e}")
        search_context = "Web search unavailable. Base analysis strictly on the job description."

    # 2. Build the strict prompt
    prompt = f"""
    Act as an elite business analyst preparing a candidate for a {job_title} interview at {company}.
    
    STRICT INSTRUCTIONS:
    - Target Job Title: {job_title} (Do NOT change, abbreviate, or substitute this title).
    - You are provided with real-world Web Search Context about the company below. You MUST base your "30-Second Background" and "Products & Market" sections on these real-world facts. 
    - DO NOT guess or infer the company's industry or mission just from their name. If the web search says they are a logistics company, do not call them an EdTech company.
    
    Based on the job description and the web search context, generate a concise, high-impact "Cheat Sheet".
    
    Include EXACTLY these sections:
    1. **The 30-Second Background:** Core mission and what they actually do (Ground this in the Web Search Context).
    2. **Products & Market:** Key products/services, target audience, and who their biggest competitors are.
    3. **The Inside Scoop:** Based on the job description, what specific problem or bottleneck is this company likely struggling with right now that the {job_title} role is meant to solve?
    4. **The Mic Drop:** Give me one highly insightful, strategic question the candidate can ask the interviewer at the end of the interview to completely blow their mind and show deep industry understanding.

    Web Search Context:
    {search_context}

    Job Description:
    {job_description}
    """
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        brief_text = response.text.strip()
    except Exception as e:
        print(f"      [x] Failed to generate company brief: {e}")
        return

    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54
    )
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=16, fontName="Helvetica-Bold", textColor=colors.HexColor("#0F172A"), spaceAfter=15)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10.5, leading=15.5, textColor=colors.HexColor("#1E293B"), spaceAfter=10, fontName="Helvetica")
    
    story = []
    story.append(Paragraph(f"Executive Company Brief: {company}", title_style))
    
    for p in brief_text.split('\n\n'):
        if p.strip():
            clean = p.strip()
            while '**' in clean:
                clean = clean.replace('**', '<b>', 1).replace('**', '</b>', 1)
            story.append(Paragraph(xml_safe(clean).replace('\n', '<br/>'), body_style))
            story.append(Spacer(1, 6))
            
    doc.build(story)

def check_for_extra_requirements(client, job_description):
    """Scans the job description for non-standard application instructions."""
    prompt = f"""
    Read this job description. Does it ask the applicant to do anything outside of simply submitting a resume and cover letter through a portal? 
    For example: Does it ask to email a specific person, submit a writing sample, or provide a portfolio link? (Ignore requests for official university transcripts).
    
    If YES: Draft the required email or a short text document fulfilling the requirement.
    If NO: Output exactly "NONE".
    
    Job Description:
    {job_description}
    """
    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=prompt
    )
    return response.text.strip()

# ==========================================
# 3. MAIN EXECUTION LOOP
# ==========================================
def build_application_packages():
    print("--- INITIATING PHASE 7: AUTO-FULFILLMENT ENGINE ---")
    
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            for k, v in tomllib.load(f).items(): os.environ[k] = str(v)

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)

    resume_text = ""
    try:
        with open("master_resume.md", "r", encoding="utf-8") as f: 
            resume_text = f.read()
    except FileNotFoundError:
        print("ERROR: master_resume.md not found.")
        return

    try:
        with open("deep_jobs.json", "r") as f: passed_jobs = json.load(f)
    except FileNotFoundError: return

    if not passed_jobs: return

    # --- NEW SYNC LOGIC ---
    # Read the final email text to see which jobs actually survived the 85+ score cutoff
    try:
        with open("FINAL_STRATEGY.md", "r", encoding="utf-8") as f:
            approved_text = f.read()
    except FileNotFoundError:
        approved_text = ""

    # Filter passed_jobs down to ONLY the ones whose URL appears in the final report
    final_jobs = []
    for job in passed_jobs:
        if job.get("url", "MISSING_URL") in approved_text:
            final_jobs.append(job)

    passed_jobs = final_jobs
    
    if not passed_jobs:
        print("   [-] No jobs scored 85+. Skipping package generation.")
        return
    # ----------------------

    client = genai.Client()
    
    output_dir = "application_packages"
    
    # --- SELF CLEANING MECHANISM ---
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir) # Nuke the old folder and all its contents
    
    os.makedirs(output_dir, exist_ok=True) # Rebuild a fresh, empty folder
    # -------------------------------
        
    print(f"Drafting full upload-ready documents for {len(passed_jobs)} roles...")

    for i, job in enumerate(passed_jobs):
        job_title = job.get("title", job.get("job_title", job.get("query_matched", "Unknown Role")))
        raw_jd = "\n".join(job.get("raw_text", []))
        
        prompt = f"""
        You are an elite executive career coach and ATS optimization expert. Read this raw job data and candidate master resume.
        Raw Job Data: {raw_jd}
        Master Kitchen-Sink Resume: {resume_text}
        
        TASK REQUIREMENTS:
        Output EXACTLY three parts separated by '|||'. 
        CRITICAL: Do NOT output conversational filler. Start immediately with the requested text.
        
        PART 1: Extract ONLY the official, clean company name from the raw job data.
        |||
        PART 2: The COMPLETE, TAILORED RESUME. 
        - Keep my Name, Contact Info, Education, and Skills exactly as formatted.
        - PRUNE: Delete older or irrelevant jobs/projects/leadership roles if they do not add direct value to this specific role, ensuring the final resume is highly targeted and fits on one page.
        - REWRITE: For the projects/experience you keep, rewrite the bullet points from scratch to aggressively match the tech stack, verbs, and keywords in the Job Data.
        - FORMAT: You must strictly use the exact Markdown tags provided (# Name, ## SECTIONS, ### Roles | Dates, - bullets). Do not break this formatting.
        |||
        PART 3: Write a confident, direct 3-paragraph cover letter ready to send.
        """
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                res = client.models.generate_content(
                    model='gemini-2.5-flash', contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.2)
                )
                parts = res.text.split('|||')
                
                company = clean_llm_artifacts(parts[0]).strip() if len(parts) > 0 else f"Company_{i+1}"
                full_resume = clean_llm_artifacts(parts[1]).strip() if len(parts) > 1 else resume_text
                letter_text = clean_llm_artifacts(parts[2]).strip() if len(parts) > 2 else res.text
                
                clean_comp = re.sub(r'[^\w\s-]', '', company).strip().replace(' ', '_')
                
                # 1 & 2. Build Resume & Cover Letter
                res_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Full_Resume.pdf")
                cov_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Cover_Letter.pdf")
                build_resume_pdf(res_path, full_resume)
                build_letter_pdf(cov_path, company, letter_text)
                
                # 3. Build Interview Prep PDF
                prep_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Interview_Prep.pdf")
                build_interview_prep_pdf(prep_path, company, job_title, raw_jd, client)
                
                # 4. Build Company Brief PDF
                brief_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Company_Brief.pdf")
                build_company_brief_pdf(brief_path, company, job_title, raw_jd, client)
                
                # 5. Check for Edge-Case Requirements
                extra_reqs = check_for_extra_requirements(client, raw_jd)
                if "NONE" not in extra_reqs.upper() and len(extra_reqs) > 10:
                    extra_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Extra_Steps.txt")
                    with open(extra_path, "w", encoding="utf-8") as ef:
                        ef.write(extra_reqs)
                    print(f"   [!] Extra requirements found for {company}. Saved to {extra_path}")

                print(f"   [+] Compiled upload-ready ATS PDFs for: {job_title} at {company}")
                
                time.sleep(3)
                break 
                
            except Exception as e:
                if any(err in str(e) for err in ["503", "UNAVAILABLE", "429"]):
                    wait_s = (attempt + 1) * 10
                    print(f"   [!] Google API busy on Job {i+1} (Attempt {attempt+1}/{max_retries}). Holding {wait_s}s...")
                    time.sleep(wait_s)
                else:
                    print(f"   [!] Fatal error on {job_title}: {e}")
                    break

if __name__ == "__main__":
    build_application_packages()