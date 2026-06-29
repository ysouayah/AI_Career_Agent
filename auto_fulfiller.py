from google import genai
from google.genai import types
import os
import json
import sys
import tomllib
import re
import time
from resume_parser import extract_resume_text
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

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

def build_resume_pdf(filename, markdown_resume):
    """Compiles a tight, 0.5-inch margined full ATS Resume PDF."""
    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    
    # ATS Resume Typography Hierarchy
    name_style = ParagraphStyle('ResName', parent=styles['Heading1'], fontSize=18, leading=22, alignment=1, textColor=colors.HexColor("#0F172A"), fontName="Helvetica-Bold")
    contact_style = ParagraphStyle('ResContact', parent=styles['Normal'], fontSize=9, leading=13, alignment=1, textColor=colors.HexColor("#475569"), spaceAfter=12)
    section_style = ParagraphStyle('ResSection', parent=styles['Heading2'], fontSize=11, leading=15, textColor=colors.HexColor("#1E3A8A"), spaceBefore=12, spaceAfter=4, fontName="Helvetica-Bold")
    role_style = ParagraphStyle('ResRole', parent=styles['Normal'], fontSize=10, leading=14, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#0F172A"))
    bullet_style = ParagraphStyle('ResBullet', parent=styles['Normal'], fontSize=9.5, leading=13.5, leftIndent=14, firstLineIndent=-9, spaceAfter=3, textColor=colors.HexColor("#334155"))
    
    story = []
    for line in markdown_resume.split('\n'):
        line = line.strip()
        if not line: continue
        
        # Convert standard markdown bolding
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
    """Compiles a classic, 0.75-inch margined Cover Letter PDF."""
    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54
    )
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('CovTitle', parent=styles['Heading1'], fontSize=15, leading=19, textColor=colors.HexColor("#0F172A"), spaceAfter=18, fontName="Helvetica-Bold")
    body_style = ParagraphStyle('CovBody', parent=styles['Normal'], fontSize=10.5, leading=15.5, textColor=colors.HexColor("#334155"), spaceAfter=10, fontName="Helvetica")
    
    story = [Paragraph(f"Application Cover Letter &mdash; {company}", title_style), Spacer(1, 10)]
    for p in letter_text.split('\n\n'):
        if p.strip():
            clean = p.strip()
            while '**' in clean:
                clean = clean.replace('**', '<b>', 1).replace('**', '</b>', 1)
            story.append(Paragraph(xml_safe(clean).replace('\n', '<br/>'), body_style))
            story.append(Spacer(1, 6))
            
    doc.build(story)

def build_application_packages():
    print("--- INITIATING PHASE 7: AUTO-FULFILLMENT ENGINE ---")
    
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            for k, v in tomllib.load(f).items(): os.environ[k] = str(v)

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)
    
    try:
        with open("sifted_jobs.json", "r") as f: passed_jobs = json.load(f)
    except FileNotFoundError: return

    if not passed_jobs: return

    resume_text = extract_resume_text("resume.pdf")
    client = genai.Client()
    
    output_dir = "application_packages"
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Drafting full upload-ready documents for {len(passed_jobs)} roles...")

    for i, job in enumerate(passed_jobs):
        job_title = job.get("query_matched", "Unknown Role")
        raw_jd = "\n".join(job.get("raw_text", []))
        
        prompt = f"""
        You are an elite executive career coach and ATS optimization expert. Read this raw job data and candidate master resume.
        Raw Job Data: {raw_jd}
        Master Resume: {resume_text}
        
        TASK REQUIREMENTS:
        Output EXACTLY three parts separated by '|||'. 
        CRITICAL: Do NOT output conversational filler. Start immediately with the requested text.
        
        PART 1: Extract ONLY the official, clean company name from the raw job data (e.g. SentiLink, Qualcomm, Max Tech). Nothing else.
        |||
        PART 2: The COMPLETE, FULL TAILORED RESUME. Take my master resume verbatim from top to bottom, but rewrite 3 to 4 bullet points in my Experience/Projects section to aggressively match this job's exact tech stack. Keep my name, contact info, education, skills, and dates 100% intact. Format strictly with Markdown tags (# Name, ## SECTIONS, ### Roles | Dates, - bullets).
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
                
                res_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Full_Resume.pdf")
                cov_path = os.path.join(output_dir, f"Job{i+1}_{clean_comp}_Cover_Letter.pdf")
                
                build_resume_pdf(res_path, full_resume)
                build_letter_pdf(cov_path, company, letter_text)
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