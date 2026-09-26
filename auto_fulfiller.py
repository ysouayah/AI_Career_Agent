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
from ddgs import DDGS

# ==========================================
# 1. TEXT FORMATTING UTILS
# ==========================================
def xml_safe(text):
    """Escapes special characters so ReportLab XML doesn't crash on symbols like & or <.
    <b> and <i> survive; everything else is escaped."""
    for tag, token in (('<b>', '§B§'), ('</b>', '§/B§'), ('<i>', '§I§'), ('</i>', '§/I§')):
        text = text.replace(tag, token)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    for tag, token in (('<b>', '§B§'), ('</b>', '§/B§'), ('<i>', '§I§'), ('</i>', '§/I§')):
        text = text.replace(token, tag)
    return text


def md_inline(line):
    """**bold** -> <b>, *italic* -> <i>. Italics used to print as literal asterisks.
    A bullet marker ("* text") is never mistaken for italics: it's followed by a space."""
    while line.count('**') >= 2:
        line = line.replace('**', '<b>', 1).replace('**', '</b>', 1)
    return re.sub(r'(?<![*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?![*\w])', r'<i>\1</i>', line)

def url_matches(url, text):
    """Job boards append tracking params, and the model often drops them when
    copying a URL into the report. Match on the bare URL, then on the numeric
    job ID, before giving up."""
    if not url:
        return False
    base = url.split("?")[0].split("#")[0].rstrip("/")
    if base and base in text:
        return True
    if url in text:
        return True
    for job_id in re.findall(r"\d{6,}", base):
        if job_id in text:
            return True
    return False


def clean_llm_artifacts(text):
    """Scrubs out leaked AI conversational filler or markdown code block wrappers."""
    lines = text.replace("```markdown", "").replace("```", "").split('\n')
    cleaned = []
    for line in lines:
        if re.match(r'^(PART \d|SECTION \d|\* PART|\*\*PART)', line.strip(), re.IGNORECASE):
            continue
        cleaned.append(line)
    out = '\n'.join(cleaned).strip()

    # Strip leaked assistant voice from the opening lines (e.g. "Okay, I can act as...",
    # "As an elite business analyst, I've prepared...", "Here are 15 questions...").
    preamble = re.compile(
        r'^\s*(okay|sure|certainly|of course|absolutely|got it|understood|here(\'s| is| are)|'
        r'as an? (elite|senior|experienced)|i (can|will|have|\'ve)|below (is|are)|'
        r'i\'ll (act|generate|prepare))\b',
        re.IGNORECASE)
    blocks = out.split('\n\n')
    while blocks and preamble.match(blocks[0].strip()):
        blocks.pop(0)
    return '\n\n'.join(blocks).strip()

# ==========================================
# 2. PDF & CONTENT GENERATORS
# ==========================================
def build_resume_pdf(filename, markdown_resume, compact=False):
    """Compiles a tight, 0.5-inch margined full ATS Resume PDF. Returns the page count.
    compact=True keeps the same design with tighter vertical spacing -- the first thing tried
    when a resume spills onto a second page."""
    margin = 30 if compact else 36
    doc = SimpleDocTemplate(
        filename, pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=margin, bottomMargin=margin
    )
    styles = getSampleStyleSheet()
    c = compact
    name_style = ParagraphStyle('ResName', parent=styles['Heading1'], fontSize=17 if c else 18, leading=20 if c else 22, alignment=1, textColor=colors.HexColor("#0F172A"), fontName="Helvetica-Bold")
    contact_style = ParagraphStyle('ResContact', parent=styles['Normal'], fontSize=9, leading=13, alignment=1, textColor=colors.HexColor("#475569"), spaceAfter=6 if c else 12)
    section_style = ParagraphStyle('ResSection', parent=styles['Heading2'], fontSize=11, leading=13 if c else 15, textColor=colors.HexColor("#1E3A8A"), spaceBefore=7 if c else 12, spaceAfter=3 if c else 4, fontName="Helvetica-Bold")
    role_style = ParagraphStyle('ResRole', parent=styles['Normal'], fontSize=10, leading=12.5 if c else 14, fontName="Helvetica-Bold", spaceBefore=4 if c else 6, spaceAfter=1 if c else 2, textColor=colors.HexColor("#0F172A"))
    bullet_style = ParagraphStyle('ResBullet', parent=styles['Normal'], fontSize=9.3 if c else 9.5, leading=12.2 if c else 13.5, leftIndent=14, firstLineIndent=-9, spaceAfter=1.5 if c else 3, textColor=colors.HexColor("#334155"))

    story = []
    for line in markdown_resume.split('\n'):
        line = line.strip()
        if not line: continue

        safe_line = xml_safe(md_inline(line))

        if safe_line.startswith('# '):
            story.append(Paragraph(safe_line[2:], name_style))
        elif safe_line.startswith('## '):
            story.append(Spacer(1, 1 if c else 4))
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
    return doc.page

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



    # Guarantee a sign-off: the model frequently omits it.
    if not re.search(r'(sincerely|best regards|kind regards|respectfully|warm regards)',
                     letter_text.strip()[-250:], re.IGNORECASE):
        story.append(Spacer(1, 10))
        story.append(Paragraph("Sincerely,", body_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Youssef Souayah</b>", body_style))

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

    - Output ONLY the questions. No preamble, no meta-commentary, no explanation of your approach.
      Do not comment on the quality or completeness of the job description.

    Based on the following job description, generate 15 highly specific interview questions to prepare the candidate. 
    Include 5 Technical/Hard Skill questions, 5 Behavioral/Cultural questions, and 5 Strategic/Scenario-based questions.
    
    Job Description:
    {job_description}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=prompt
    )
    prep_text = clean_llm_artifacts(response.text)

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

def build_company_brief_pdf(filename, company, job_title, job_description, client, location=""):
    """Generates a deep-dive company brief to give the candidate an interview edge, grounded in a live web search."""
    
    # 1. Fetch real-world context using DuckDuckGo
    search_context = ""
    try:
        # A bare company name collides ("Sentinel Group" also names a security firm), so the
        # search carries the role's location. The prompt below discards off-target results.
        where = location.split(",")[0].strip() if location else ""
        results = DDGS().text(f'"{company}" {where} {job_title} company'.strip(), max_results=5)
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
    - Output ONLY the brief. No preamble, no meta-commentary, and no notices about
      missing or unavailable web data. If web context is thin, simply write less.
    - You are provided with real-world Web Search Context about the company below. You MUST base your "30-Second Background" and "Products & Market" sections on these real-world facts. 
    - DO NOT guess or infer the company's industry or mission just from their name. If the web search says they are a logistics company, do not call them an EdTech company.
    - Several companies can share a name. The JOB DESCRIPTION is the authority on what this
      employer does. Discard any search result that describes a different business (a
      different industry, headquarters, or product line). If no result clearly matches the
      employer in the job description, base the brief on the job description alone.
    
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
        brief_text = clean_llm_artifacts(response.text)
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
# 3. RESUME ORDER ENFORCEMENT
# ==========================================
def _header_tokens(line):
    return set(re.findall(r"[a-z0-9]+", line.lower()))


def enforce_entry_order(tailored, master):
    """Puts ### entries back in master-resume order within each ## section.

    The master resume is reverse-chronological. The prompt forbids moving entries, but models
    reorder by relevance often enough that it is checked here. Each tailored entry is matched to
    its master header by word overlap; if any entry can't be matched confidently, that section
    is left as the model wrote it rather than guessed at."""
    master_headers = [l.strip() for l in master.split("\n") if l.strip().startswith("### ")]

    def master_index(header):
        toks = _header_tokens(header)
        best, best_score = None, 0.0
        for i, m in enumerate(master_headers):
            mt = _header_tokens(m)
            score = len(toks & mt) / max(len(toks | mt), 1)
            if score > best_score:
                best, best_score = i, score
        return best if best_score >= 0.5 else None

    sections, current = [], []
    for line in tailored.split("\n"):
        if line.strip().startswith("## "):
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    sections.append(current)

    out = []
    for sec in sections:
        head, entries = [], []
        for line in sec:
            if line.strip().startswith("### "):
                entries.append([line])
            elif entries:
                entries[-1].append(line)
            else:
                head.append(line)
        if len(entries) > 1:
            idx = [master_index(e[0]) for e in entries]
            if None in idx or len(set(idx)) != len(idx):
                name = head[0].strip() if head else "(untitled section)"
                print(f"      [?] Could not match every entry in {name} to the master resume; "
                      f"order left as generated.")
            elif idx != sorted(idx):
                entries = [e for _, e in sorted(zip(idx, entries), key=lambda p: p[0])]
                print(f"      [~] Model reordered entries in {head[0].strip() if head else 'a section'}; "
                      f"restored reverse-chronological order.")
        out.extend(head)
        for e in entries:
            out.extend(e)
    return "\n".join(out)


# ==========================================
# 3b. GROUNDING CHECKS
# ==========================================
# Tailoring kept tacking justifications onto real bullets ("..., demonstrating strong analytical
# skills", "akin to quality assurance") and flattening numbers ("78% more" -> "significant
# improvements"). The prompt forbids both; these checks enforce it against the master text.
FILLER_LEAD = re.compile(
    r"^(demonstrating|showcasing|highlighting|underscoring|reflecting|akin to|contributing to|"
    r"enhancing|ensuring|effectively|facilitating|supporting|providing|solving|improving|"
    r"significantly|dramatically|thereby)\b", re.IGNORECASE)
NUMBER = re.compile(r"[+-]?\d[\d,.]*%?\+?")
# Metrics worth protecting: percentages, signed or decimal figures, and "80+"-style counts.
# Plain integers (course codes, "4 core dimensions") may be trimmed with their clause.
METRIC = re.compile(r"[+-]\d[\d,.]*%?|\d[\d,]*\.\d+%?|\d[\d,]*%|\d[\d,]*\+")


def _norm_text(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%+.\s]", " ", t.lower())).strip()


def _content_tokens(t):
    return {w for w in re.findall(r"[a-z]{4,}", t.lower())}


def _master_bullets(master):
    return [l.strip()[2:] for l in master.split("\n") if l.strip().startswith(("- ", "* "))]


def strip_unsourced_tails(tailored, master):
    """Removes trailing ", demonstrating X"-style clauses that don't appear in the master
    resume. A tail that IS in the master (e.g. "dramatically increasing outbound pipeline
    efficiency") is the candidate's own wording and stays."""
    master_norm = _norm_text(master)
    out, removed = [], 0
    for line in tailored.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            body = stripped[2:].rstrip()
            end = "." if body.endswith(".") else ""
            core = body[:-1] if end else body
            while True:
                # The last ", X" or " and X" clause; stop at the first one that is real content.
                cut = max(core.rfind(", "), core.rfind(" and "))
                if cut < 0:
                    break
                sep_len = 2 if core.startswith(", ", cut) else 5
                head, tail = core[:cut], core[cut + sep_len:]
                if not FILLER_LEAD.match(tail) or _norm_text(tail) in master_norm:
                    break
                core, removed = head, removed + 1
            line = line[: len(line) - len(line.lstrip())] + stripped[:2] + core + end
        out.append(line)
    if removed:
        print(f"      [~] Stripped {removed} filler clause(s) not found in the master resume.")
    return "\n".join(out)


def restore_dropped_numbers(tailored, master):
    """If a tailored bullet is clearly a rewrite of a master bullet but has lost that bullet's
    numbers, the master bullet goes back in verbatim."""
    masters = [(b, set(METRIC.findall(b)), _content_tokens(b)) for b in _master_bullets(master)]
    out, restored = [], 0
    for line in tailored.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            body, toks = stripped[2:], _content_tokens(stripped[2:])
            best, best_score = None, 0.0
            nums = set(METRIC.findall(body))
            for m in masters:
                score = len(toks & m[2]) / max(len(toks | m[2]), 1)
                if nums & m[1]:
                    score += 0.3   # sharing a specific figure like "+1.51" is strong evidence of the pairing
                if score > best_score:
                    best, best_score = m, score
            if best and best_score >= 0.35 and best[1] and not best[1] <= nums:
                line = line[: len(line) - len(line.lstrip())] + stripped[:2] + best[0]
                restored += 1
        out.append(line)
    if restored:
        print(f"      [~] Restored {restored} bullet(s) whose numbers had been generalized away.")
    return "\n".join(out)


def unsourced_numbers(text, master):
    """Numbers in generated text that never appear in the master resume -- likely invented."""
    known = set(NUMBER.findall(master))
    return sorted({n for n in NUMBER.findall(text) if n not in known and len(n.strip("+-.,%")) > 0
                   and not re.fullmatch(r"20\d\d", n)})


def ground_resume(tailored, master):
    tailored = enforce_entry_order(tailored, master)
    tailored = restore_dropped_numbers(tailored, master)   # first, while the rewrite still resembles its source
    tailored = strip_unsourced_tails(tailored, master)
    invented = unsourced_numbers(tailored, master)
    if invented:
        print(f"      [!] Numbers not in the master resume: {', '.join(invented)} -- check before sending.")
    return tailored, invented


def _month_year(ym, fallback):
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%B %Y")
    except (TypeError, ValueError):
        return fallback


try:
    with open("user_config.json", "r", encoding="utf-8") as _f:
        _facts = json.load(_f).get("candidate_facts", {})
except (FileNotFoundError, json.JSONDecodeError):
    _facts = {}
GRADUATION = _month_year(_facts.get("graduation"), "May 2027")
EARLIEST_START = _month_year(_facts.get("earliest_start"), "September 2027")

SOURCE_CLAIM = re.compile(
    r",?\s*(as|which I saw|that I found)\s+(advertised|posted|listed|found|seen)\s+on\s+"
    r"(LinkedIn|Indeed|Handshake|Glassdoor|ZipRecruiter|your (careers|company) (site|website|page))",
    re.IGNORECASE)


def scrub_letter(text):
    """The model doesn't know where a posting was found, and kept saying LinkedIn anyway."""
    return SOURCE_CLAIM.sub("", text)


def fit_resume_to_one_page(client, path, resume_md, master):
    """Build; if it spills over, retry compact; if still over, ask the model to cut (never
    move or reword), re-ground, and rebuild. Returns the final page count."""
    pages = build_resume_pdf(path, resume_md)
    if pages <= 1:
        return pages
    pages = build_resume_pdf(path, resume_md, compact=True)
    for _ in range(2):
        if pages <= 1:
            return pages
        prompt = f"""This resume runs onto a second page. Delete the least relevant bullets or
        entries so it fits on one page. Rules: only DELETE whole bullets or whole entries; never
        reword, reorder, or add anything; keep every ## section and at least one Leadership entry.
        Output ONLY the full revised resume in the same Markdown.

        {resume_md}"""
        try:
            res = client.models.generate_content(
                model='gemini-2.5-flash', contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0))
            resume_md, _ = ground_resume(clean_llm_artifacts(res.text).strip(), master)
        except Exception as e:
            print(f"      [!] Could not shorten resume: {e}")
            break
        pages = build_resume_pdf(path, resume_md, compact=True)
    if pages > 1:
        print(f"      [!] Resume is still {pages} pages: {os.path.basename(path)} -- trim by hand.")
    return pages


# ==========================================
# 4. ONE APPLICATION PACKAGE
# ==========================================
def build_package(client, job, label, output_dir, resume_text):
    """Builds the four PDFs (plus any extra-steps note) for one job. Returns True on success."""
    # The deep scrape lives in full_description. raw_text is only the 5-line preview card.
    raw_jd = job.get("full_description") or ""

    # Never generate documents from an empty or stub description.
    if len(raw_jd) < 500:
        print(f"   [!] SKIPPED {job.get('url', 'unknown URL')} -- description is only "
              f"{len(raw_jd)} chars. Deep scrape likely failed for this URL.")
        return False

    # Real title comes from the listing card. query_matched is a SEARCH QUERY, never a title.
    card = job.get("raw_text") or []
    job_title = (job.get("title") or job.get("job_title")
                 or (card[0] if card else "") or "Unknown Role").strip()

    # A role hiring for a later cohort already expects a post-graduation start; anything else
    # gets the start date stated plainly, so nobody is surprised three rounds in.
    track = (job.get("requirements") or {}).get("hiring_track")
    availability_rule = ("" if track == "campus_cohort" else
        f"- State once, plainly, that the candidate graduates in {GRADUATION} and is available "
        f"to start in {EARLIEST_START}.")

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
    - ORDER IS FIXED: Keep every section, and every entry (each ### line) within a section,
      in the SAME ORDER as the master resume, which is reverse-chronological. Never move an
      entry above another one, even if it is more relevant to this job. Copy each ### header
      line exactly as written in the master resume.
    - PRUNE: Cut the least relevant experience, projects, and leadership entries so the
      result fits one page. Removing an entry is allowed; moving one is not. Keep at least one
      leadership entry -- never delete the whole Leadership section.
    - WITHIN an entry, you MAY reorder its bullets so the most relevant come first, and REFRAME
      them so the language echoes the job description where it HONESTLY applies. Bullets never
      move from one entry to another. In Leadership entries, the italic positions line stays
      the first line under its header.

    ABSOLUTE GROUNDING RULE -- this overrides every other instruction:
    Every claim must be traceable to the master resume. You may reword, reorder, shorten,
    and re-emphasize. You may NOT:
      * add a skill, tool, language, framework, certification, or coursework that does not
        appear in the master resume;
      * claim experience in a domain (finance, healthcare, defence, etc.) the master resume
        does not show;
      * invent or inflate metrics, dates, scope, team sizes, or job titles.
    If the job asks for something the candidate does not have, LEAVE IT OUT. An honest gap
    is recoverable; a fabricated qualification is not.

    - PRESERVE SPECIFICS: Keep concrete numbers, named tools, named organisations, and named
      methods exactly as written in the master resume. Do not generalise "Apollo" into
      "external APIs", "+1.51 pts vs +0.85" into "significant improvement", or
      "LinkedIn, Indeed, and Handshake" into "multiple job boards". Specificity is what
      makes the resume credible and what ATS keyword matching depends on.
    - NO JUSTIFICATION TAILS: Never append a clause explaining why a bullet matters
      ("..., demonstrating strong analytical skills", "akin to quality assurance",
      "ensuring alignment with business goals"). A bullet states what was done and its result.
    - LENGTH: The resume must fit on ONE page. When in doubt, cut another bullet.
    - FORMAT: You must strictly use the exact Markdown tags provided (# Name, ## SECTIONS, ### Roles | Dates, - bullets). Do not break this formatting.
    |||
    PART 3: Write a confident, direct 3-paragraph cover letter ready to send.
    - The SAME GROUNDING RULE applies. Every skill, course, and experience you cite must
      appear in the master resume. Do not claim knowledge of a technique the resume does not
      evidence, and do not manufacture enthusiasm for an industry the candidate has no
      stated connection to.
    - Write about what the candidate HAS done and why it transfers. Do not assert domain
      expertise they lack; where a gap is obvious, show transferable reasoning instead of
      papering over it.
    - Open with "Dear Hiring Team,". Do not say where the posting was found ("as advertised
      on LinkedIn") -- you do not know.
    - Do not quote the posting's phrases back in quotation marks, and do not grade the fit
      yourself ("align perfectly", "precisely the type of candidate you are seeking").
    {availability_rule}
    - End with "Sincerely," on its own line, then the candidate's name. Do not add a
      postscript or any commentary after the signature.
    """

    max_retries = 5
    for attempt in range(max_retries):
        try:
            res = client.models.generate_content(
                model='gemini-2.5-flash', contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            parts = res.text.split('|||')

            company = clean_llm_artifacts(parts[0]).strip() if len(parts) > 0 else f"Company_{label}"
            full_resume = clean_llm_artifacts(parts[1]).strip() if len(parts) > 1 else resume_text
            full_resume, _ = ground_resume(full_resume, resume_text)
            letter_text = clean_llm_artifacts(parts[2]).strip() if len(parts) > 2 else res.text
            letter_text = scrub_letter(letter_text)

            clean_comp = re.sub(r'[^\w\s-]', '', company).strip().replace(' ', '_')
            stem = os.path.join(output_dir, f"{label}_{clean_comp}")

            # 1 & 2. Resume & Cover Letter
            fit_resume_to_one_page(client, f"{stem}_Full_Resume.pdf", full_resume, resume_text)
            build_letter_pdf(f"{stem}_Cover_Letter.pdf", company, letter_text)

            # 3. Interview Prep
            build_interview_prep_pdf(f"{stem}_Interview_Prep.pdf", company, job_title, raw_jd, client)

            # 4. Company Brief
            build_company_brief_pdf(f"{stem}_Company_Brief.pdf", company, job_title, raw_jd, client,
                                    location=job.get("location") or "")

            # 5. Edge-case requirements
            extra_reqs = check_for_extra_requirements(client, raw_jd)
            if "NONE" not in extra_reqs.upper() and len(extra_reqs) > 10:
                extra_path = f"{stem}_Extra_Steps.txt"
                with open(extra_path, "w", encoding="utf-8") as ef:
                    ef.write(extra_reqs)
                print(f"   [!] Extra requirements found for {company}. Saved to {extra_path}")

            print(f"   [+] Compiled upload-ready ATS PDFs for: {job_title} at {company}")
            time.sleep(3)
            return True

        except Exception as e:
            if any(err in str(e) for err in ["503", "UNAVAILABLE", "429"]):
                wait_s = (attempt + 1) * 10
                print(f"   [!] Google API busy on {label} (Attempt {attempt+1}/{max_retries}). Holding {wait_s}s...")
                time.sleep(wait_s)
            else:
                print(f"   [!] Fatal error on {job_title}: {e}")
                return False
    return False


# ==========================================
# 5. MAIN EXECUTION
# ==========================================
NEAR_MISS_FILE = "near_miss_jobs.json"
NEAR_MISS_DIR = "near_miss_packages"   # separate from application_packages, which the weekly run wipes


def select_near_misses(records, requests):
    """Requests are labels ("N2" or "2"), "all", or any fragment of a job URL."""
    if any(r.lower() == "all" for r in requests):
        return list(records), []
    chosen, unknown = [], []
    for req in requests:
        want = req.upper() if req.upper().startswith("N") else f"N{req}"
        hits = [r for r in records if r.get("near_miss_label") == want]
        if not hits:
            hits = [r for r in records if req in (r.get("url") or "")]
        if hits:
            chosen.extend(h for h in hits if h not in chosen)
        else:
            unknown.append(req)
    return chosen, unknown


def build_application_packages(near_miss_requests=None):
    on_request = near_miss_requests is not None
    print("--- INITIATING AUTO-FULFILLMENT ENGINE"
          + (" (NEAR MISSES, ON REQUEST) ---" if on_request else " ---"))

    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            for k, v in tomllib.load(f).items(): os.environ[k] = str(v)

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not found.")
        sys.exit(1)

    try:
        with open("master_resume.md", "r", encoding="utf-8") as f:
            resume_text = f.read()
    except FileNotFoundError:
        print("ERROR: master_resume.md not found.")
        return

    if on_request:
        if not near_miss_requests:
            print("   Usage: python auto_fulfiller.py --near-miss N1 N3   (or: --near-miss all)")
            return
        try:
            with open(NEAR_MISS_FILE, "r") as f:
                records = json.load(f)
        except FileNotFoundError:
            print(f"   [-] {NEAR_MISS_FILE} not found. It is written by run_everything.py; "
                  f"run from the same folder as the weekly run.")
            return
        jobs, unknown = select_near_misses(records, near_miss_requests)
        if unknown:
            available = ", ".join(r.get("near_miss_label", "?") for r in records) or "none"
            print(f"   [!] Not found in this week's near misses: {', '.join(unknown)}. Available: {available}")
        if not jobs:
            return
        output_dir = NEAR_MISS_DIR
        os.makedirs(output_dir, exist_ok=True)   # additive: earlier requests are kept
        labelled = [(j.get("near_miss_label", f"N{i+1}"), j) for i, j in enumerate(jobs)]
    else:
        # run_everything.py writes approved_jobs.json -- the exact jobs that cleared the grader.
        # Reading that list, rather than scanning the report for URLs, keeps near-miss links in
        # the email from triggering package generation.
        try:
            with open("approved_jobs.json", "r") as f:
                jobs = json.load(f)
        except FileNotFoundError:
            print("   [-] approved_jobs.json not found. Skipping package generation.")
            return
        output_dir = "application_packages"
        # Self-cleaning: last week's packages must never ride along with this week's.
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        if not jobs:
            print("   [-] No jobs cleared the grader. Skipping package generation.")
            return
        labelled = [(f"Job{i+1}", j) for i, j in enumerate(jobs)]

    client = genai.Client()
    print(f"Drafting full upload-ready documents for {len(labelled)} roles...")

    built = 0
    for label, job in labelled:
        if build_package(client, job, label, output_dir, resume_text):
            built += 1
            if on_request and job.get("url"):
                # Packaged means never resurfaced -- same as an approved job.
                from database_manager import init_db, mark_job_packaged
                init_db()
                mark_job_packaged(job["url"])
    print(f"Done: {built} of {len(labelled)} package(s) written to {output_dir}/")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--near-miss" in args:
        build_application_packages(near_miss_requests=args[args.index("--near-miss") + 1:])
    else:
        build_application_packages()