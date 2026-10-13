from google import genai
from google.genai import types
import os
import json
import sys
import tomllib
import re
import io
import copy
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
def build_resume_pdf(filename, markdown_resume, compact=False, pagesize=letter):
    """Compiles a tight, 0.5-inch margined full ATS Resume PDF. Returns the page count.
    compact=True keeps the same design with tighter vertical spacing -- the first thing tried
    when a resume spills onto a second page. filename may be an io.BytesIO, which is how the
    one-page fit measures a draft without writing it."""
    margin = 30 if compact else 36
    doc = SimpleDocTemplate(
        filename, pagesize=pagesize,
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
    
    name_style = ParagraphStyle('Name', parent=styles['Normal'], fontSize=16, leading=20, fontName="Helvetica-Bold", textColor=colors.HexColor("#0F172A"), spaceAfter=4)
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
# "Gemini 2.5 Flash" is a product version, not a result. Counting it as a metric put the full
# 375-character master bullet back whenever the model shortened that bullet.
VERSION = re.compile(r"\b[A-Z][A-Za-z]+ \d+\.\d+\b")


def _metrics(text):
    return set(METRIC.findall(VERSION.sub(" ", text)))


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
    masters = [(b, _metrics(b), _content_tokens(b)) for b in _master_bullets(master)]
    out, restored = [], 0
    for line in tailored.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            body, toks = stripped[2:], _content_tokens(stripped[2:])
            best, best_score = None, 0.0
            nums = _metrics(body)
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
    known = {n.rstrip(".,") for n in NUMBER.findall(master)}
    found = {n.rstrip(".,") for n in NUMBER.findall(text)}   # "2026," at the end of a clause is 2026
    return sorted({n for n in found if n not in known and len(n.strip("+-.,%")) > 0
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


# ==========================================
# 3c. WHAT THE POSTING ASKS FOR
# ==========================================
# The CRA Economics package (10/12) ignored three things its posting states outright: put an
# address on the resume, name a practice and a location in the letter, and a research
# apprenticeship is highly desired. Nothing read the posting for instructions, so they are now
# extracted once, each with a quote that must appear in the posting, and enforced in code.
def _norm_quote(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def quote_found(quote, text):
    """Same rule as the hard rules in run_everything.py (not imported: that module runs pipeline
    setup on import). A claim about the posting counts only if its quote is in the posting."""
    q = _norm_quote(quote)
    return len(q) >= 8 and q in _norm_quote(text)


def call_json(client, prompt):
    res = client.models.generate_content(
        model='gemini-2.5-flash', contents=prompt,
        config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json"))
    return json.loads(res.text)


def looks_truncated(jd):
    """Handshake's collapsed description: the job text stops at "..." with a "More" button under
    it. Through 10/12 that is what the deep scrape saved, so the documents were written from the
    posting's first lines."""
    m = re.search(r"Job description(.*?)(What they're looking for|What this job offers|"
                  r"About the employer|$)", jd, re.S)
    return bool(m and re.search(r"(\.\.\.|…)\s*\n\s*More\s*\n", m.group(1) + "\n"))


NO_ASKS = {"role_type": "", "contact_items": [], "letter_asks": [], "valued_experience": [],
           "named_options": []}


def read_posting_asks(client, jd):
    """What the posting tells applicants to do or says it values. Every item needs a verbatim
    quote; one without it is dropped, so a posting with no instructions yields empty lists."""
    prompt = f"""Read this job posting and report ONLY what it states. Return JSON:
    {{"role_type": "<3 to 6 words naming the kind of work, e.g. 'economics litigation consulting', 'product data analytics', 'backend software engineering'>",
      "contact_items": [{{"item": "address" | "phone" | "email", "quote": "..."}}],
      "letter_asks": [{{"ask": "<one thing the applicant is told to state or describe in the cover letter>", "kind": "practice_or_team" | "location" | "other", "quote": "..."}}],
      "valued_experience": [{{"what": "<a kind of past experience the posting says it wants or prefers, e.g. 'research apprenticeship', 'honors thesis'>", "quote": "..."}}],
      "named_options": [{{"name": "<a practice, team or track the posting lists as hiring>", "locations": ["<city>"]}}]}}
    Rules:
    - contact_items: only details the posting tells applicants to put on the resume.
    - letter_asks: only explicit instructions about the cover letter or application statement.
      One entry per separate thing: "a practice and/or a location preference" is two entries.
    - valued_experience: a specific kind of prior experience the posting names as desired or
      preferred (a thesis, a research apprenticeship, an internship in a named field). Not
      tools, soft skills, general interest in the field, or the degree itself. At most 3.
    - named_options: only when the posting lists practices, teams or tracks to choose among.
    - Every quote is copied word for word from the posting, 25 words at most. If you cannot
      quote it, leave the item out. Empty lists are the normal answer for most postings.

    Posting:
    {jd}"""
    try:
        raw = call_json(client, prompt)
    except (ValueError, TypeError, AttributeError) as e:
        print(f"      [!] Could not read the posting's application instructions: {e}")
        return None
    if not isinstance(raw, dict):
        return None

    def quoted(key):
        return [x for x in raw.get(key) or [] if isinstance(x, dict) and quote_found(x.get("quote"), jd)]

    jd_norm = _norm_quote(jd)
    options = []
    for o in raw.get("named_options") or []:
        name = _norm_quote(o.get("name")) if isinstance(o, dict) else ""
        if name and name in jd_norm:
            options.append({"name": str(o["name"]).strip(),
                            "locations": [str(l) for l in o.get("locations") or []
                                          if _norm_quote(str(l)) and _norm_quote(str(l)) in jd_norm]})
    return {"role_type": str(raw.get("role_type") or "").strip(),
            "contact_items": [c for c in quoted("contact_items") if c.get("item") in ("address", "phone", "email")],
            "letter_asks": [a for a in quoted("letter_asks") if str(a.get("ask") or "").strip()],
            "valued_experience": [v for v in quoted("valued_experience") if str(v.get("what") or "").strip()][:3],
            "named_options": options}


def contact_line(master_line, asks, notes):
    """The contact line is set here, not by the model. A detail the posting asks for is added
    when it is on file; one that is not on file is reported, never invented."""
    line = master_line
    wanted = {c["item"] for c in asks["contact_items"]}
    if "address" in wanted:
        location = (_facts.get("location") or "").strip()
        if location and location.lower() not in line.lower():
            line = f"{line} | {location}"
        notes.append(f"Posting asks for a current address on the resume; it shows the city only ({location})."
                     if location else
                     "Posting asks for a current address on the resume; none is on file, add it by hand.")
    if "phone" in wanted and not re.search(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b", line):
        notes.append("Posting asks for a telephone number on the resume; none is on file, add it by hand.")
    return line


# ==========================================
# 3d. SELECTION BY ID AND THE ONE-PAGE FIT
# ==========================================
# Every master entry (E#), bullet (B#) and skills line (S#) is numbered. The model ranks ids for
# the role; code decides what is kept. The same ranking drives the one-page fit, which used to
# be two blind "delete the least relevant bullets" requests and then a 2-page PDF.
TAG = re.compile(r"\[([EBS]\d+)\]\s*")
PINNED_KEEP = 2          # bullets an entry keeps when the posting asks for that kind of experience
PRETAILOR_PAGES = 1.3    # the model is handed a little more than a page; tightening recovers some
DEPTH_PENALTY = 6        # an entry's 2nd, 3rd, ... bullet counts as this many places lower each
# Places added to every bullet of an entry by how well the entry fits the kind of work. Ranking
# 43 bullets came out differently on each run (Pick For Me in one CRA resume, absent from the
# next); sorting a dozen entries into three groups is a steadier judgement.
TIER_PENALTY = {"core": 0, "supporting": 8, "off_target": 1000}


def _is_bullet(text):
    return text.startswith(("- ", "* "))


def _is_positions_line(text):
    """Leadership's italic line of positions held: part of the header, never ranked or cut."""
    return bool(re.fullmatch(r"[-*] \*[^*].*\*", text.strip()))


def parse_resume(md):
    """Markdown -> {"top": [name, contact], "sections": [{"head", "lines", "entries": [{"head",
    "id", "lines"}]}]}. A line is {"text", "id"}."""
    doc = {"top": [], "sections": []}
    sec = ent = None
    for raw in md.split("\n"):
        text = raw.strip()
        if not text:
            continue
        if text.startswith("## "):
            sec, ent = {"head": text, "lines": [], "entries": []}, None
            doc["sections"].append(sec)
        elif sec is None:
            doc["top"].append(text)
        elif text.startswith("### "):
            ent = {"head": text, "id": None, "lines": []}
            sec["entries"].append(ent)
        else:
            (ent or sec)["lines"].append({"text": text, "id": None})
    return doc


def _kind(sec):
    head = sec["head"].upper()
    if "EDUCATION" in head:
        return "education"
    if "LEADERSHIP" in head:
        return "leadership"
    return "entries" if sec["entries"] else "skills"


def number_master(doc):
    """Education is never cut, so it gets no ids."""
    e = b = s = 0
    for sec in doc["sections"]:
        kind = _kind(sec)
        if kind == "skills":
            for line in sec["lines"]:
                if _is_bullet(line["text"]):
                    s += 1
                    line["id"] = f"S{s}"
        elif kind != "education":
            for ent in sec["entries"]:
                e += 1
                ent["id"] = f"E{e}"
                for line in ent["lines"]:
                    if _is_bullet(line["text"]) and not _is_positions_line(line["text"]):
                        b += 1
                        line["id"] = f"B{b}"
    return doc


def render(doc, tags=False, kinds=None):
    """Back to Markdown. tags=True prefixes each numbered line with its [id], which is how the
    model sees the resume; kinds limits the output to those section kinds."""
    def fmt(line):
        if tags and line["id"]:
            return f"{line['text'][:2]}[{line['id']}] {line['text'][2:]}"
        return line["text"]

    out = [] if kinds else list(doc["top"])
    for sec in doc["sections"]:
        if kinds and _kind(sec) not in kinds:
            continue
        out += ["", sec["head"]] + [fmt(l) for l in sec["lines"]]
        for ent in sec["entries"]:
            head = f"### [{ent['id']}] {ent['head'][4:]}" if tags and ent["id"] else ent["head"]
            out += ["", head] + [fmt(l) for l in ent["lines"]]
    return "\n".join(out).strip()


def _bullets(ent):
    return [l for l in ent["lines"] if (l["id"] or "").startswith("B")]


def drop_lowest(doc, plan):
    """Removes the lowest-ranked bullet still on the resume and returns what went, or None when
    nothing may be removed. An entry the posting asks for (pinned) keeps PINNED_KEEP bullets for
    as long as anything else can go; the page limit outranks the pin, so the protection is then
    lowered a bullet at a time. An entry leaves with its last bullet, except in Leadership, where
    the header and positions line stay until nothing else is left and one entry always remains.

    Rank alone filled the page with one or two entries (five Debate League bullets, no Spark!),
    so each further bullet of the same entry is counted DEPTH_PENALTY places lower."""
    rank = {bid: i for i, bid in enumerate(plan["ranking"])}
    worst = None
    for pinned_keep in range(PINNED_KEEP, -1, -1):
        for sec in doc["sections"]:
            for ent in sec["entries"]:
                bullets = sorted(_bullets(ent), key=lambda l: rank.get(l["id"], len(rank)))
                keep = pinned_keep if ent["id"] in plan["pinned"] else 0
                tier = TIER_PENALTY[plan["tiers"].get(ent["id"], "supporting")]
                for depth, line in enumerate(bullets):
                    r = rank.get(line["id"], len(rank)) + DEPTH_PENALTY * depth + tier
                    if depth >= keep and (worst is None or r >= worst[0]):
                        worst = (r, sec, ent, line)
        if worst:
            break
    if worst:
        _, sec, ent, line = worst
        ent["lines"] = [l for l in ent["lines"] if l is not line]
        if not _bullets(ent) and _kind(sec) != "leadership":
            sec["entries"] = [x for x in sec["entries"] if x is not ent]
            if not sec["entries"] and not sec["lines"]:
                doc["sections"] = [x for x in doc["sections"] if x is not sec]
        return line["text"][2:]
    # Last resort: bare Leadership headers, from the bottom, keeping one.
    for sec in doc["sections"]:
        if _kind(sec) == "leadership" and len(sec["entries"]) > 1:
            return sec["entries"].pop()["head"][4:]
    return None


TOOL_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#-]*")


def unnamed_tool_lines(master_doc, jd):
    """Skills lines that list tools none of which the posting names. Decided in code: asked
    three times about the same CRA posting, the model dropped the PyTorch and RAG/Playwright
    lines once, one of them once, and neither once.

    A line counts as a tools line when it names at least one tool per two items. A tool is a
    capitalised token (Python, SQL, PyTorch); the capital that merely starts a phrase
    ("Secondary research") doesn't count. The line stays if the posting names one of its tools
    or its label ("Machine Learning", "AI"). Spoken languages and certifications are never
    dropped here."""
    drop = set()
    for sec in master_doc["sections"]:
        for line in sec["lines"]:
            m = re.match(r"[-*] \*\*(.+?):\*\*\s*(.*)", line["text"])
            if not line["id"] or not m or re.search(r"spoken|certif", m.group(1), re.IGNORECASE):
                continue
            label, body = m.group(1), m.group(2)
            items = [i for i in re.split(r"[,;(]", body) if i.strip()]
            tools = set()
            for item in items:
                words = TOOL_TOKEN.findall(item)
                starts_phrase = len(words) > 1 and not re.search(r"[A-Z]", words[0][1:])
                tools |= {w for w in words[1 if starts_phrase else 0:] if re.search(r"[A-Z]", w)}
            if len(tools) * 2 < len(items):
                continue

            def in_posting(word):
                return re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", jd)

            named = any(in_posting(t) for t in tools)
            parts = [part.strip() for part in re.split(r"&|/|,", label) if part.strip()]
            labelled = any(part.lower() in jd.lower() if " " in part else part.isupper() and in_posting(part)
                           for part in parts)
            if not named and not labelled:
                drop.add(line["id"])
    return drop


def plan_selection(client, jd, asks, master_doc):
    """Asks the model to sort the master resume's entries by fit for this kind of work and rank
    its bullets. Returns ids only: {"ranking": [B ids, best first], "tiers": {E id: tier},
    "skills_drop": {S ids}, "pinned": {E ids}}. If the model's answer can't be used, the ranking
    falls back to master order and says so."""
    entries = [ent for sec in master_doc["sections"] for ent in sec["entries"] if ent["id"]]
    bullets = [l["id"] for ent in entries for l in _bullets(ent)]
    skills = {l["id"] for sec in master_doc["sections"] for l in sec["lines"] if l["id"]}
    valued = asks["valued_experience"]
    valued_text = "\n".join(f'      {i}. {v["what"]} (posting: "{v["quote"]}")'
                            for i, v in enumerate(valued)) or "      (none stated)"
    plan = {"ranking": list(bullets), "tiers": {}, "skills_drop": unnamed_tool_lines(master_doc, jd),
            "pinned": set(), "ranked": False}
    tiered = [ent["id"] for sec in master_doc["sections"] if _kind(sec) != "leadership"
              for ent in sec["entries"] if ent["id"]]
    prompt = f"""You are choosing what goes on a ONE-page resume for this job. Return JSON:
    {{"entries": {{"E1": "core" | "supporting" | "off_target"}}, "bullets_ranked": ["B7", "B2", ...], "skills_drop": ["S2"], "valued_entries": [{{"entry": "E2", "valued": 0}}]}}

    The kind of work: {asks["role_type"] or "see the posting"}.
    - entries: one label for each of {", ".join(tiered)}.
      core = the entry's work is the kind of work this role does, or its method or subject matter.
      supporting = different work that still shows something the posting asks for.
      off_target = a different kind of work that a reader for this role would wonder about, such
      as a consumer app or automation tooling on a resume for research or advisory work, or
      qualitative fieldwork on a resume for software engineering.
    - bullets_ranked: EVERY [B#] id, the most useful for THIS kind of work first. Judge by the
      work the posting describes, not by how impressive a line sounds: a bullet about technology
      this role does not use ranks low. Evidence of the methods, subject matter and deliverables
      the posting names ranks high.
    - skills_drop: a [S#] line of tools stays only if the posting names at least one of its
      tools or the work plainly uses them; otherwise drop it. Lines about research methods,
      office tools, spoken languages and certifications stay unless clearly irrelevant.
    - valued_entries: the posting says it values these kinds of experience:
{valued_text}
      List an [E#] entry only if it honestly IS that kind of experience, with the number of the
      item it matches. [] if none.

    Posting:
    {jd}

    Resume lines:
    {render(master_doc, tags=True, kinds=("entries", "leadership", "skills"))}"""
    try:
        raw = call_json(client, prompt)
    except (ValueError, TypeError, AttributeError) as e:
        print(f"      [!] Selection ranking unusable ({e}); falling back to master order.")
        return plan
    if not isinstance(raw, dict):
        return plan
    ranked = []
    for b in raw.get("bullets_ranked") or []:
        if b in bullets and b not in ranked:
            ranked.append(b)
    if ranked:
        plan["ranking"] = ranked + [b for b in bullets if b not in ranked]
        plan["ranked"] = True
    plan["skills_drop"] |= {s for s in raw.get("skills_drop") or [] if s in skills}
    labels = raw.get("entries") if isinstance(raw.get("entries"), dict) else {}
    plan["tiers"] = {e: labels[e] for e in tiered if labels.get(e) in TIER_PENALTY}
    entry_ids = {ent["id"] for ent in entries}
    for v in raw.get("valued_entries") or []:
        if (isinstance(v, dict) and v.get("entry") in entry_ids
                and isinstance(v.get("valued"), int) and 0 <= v["valued"] < len(valued)):
            plan["pinned"].add(v["entry"])
    for e in plan["pinned"]:                    # what the posting asks for is never off-target
        plan["tiers"][e] = "core"
    return plan


def select_for_tailoring(master_doc, plan):
    """The master resume cut down, by rank, to what could plausibly fit: the part handed to the
    model for rewording."""
    doc = copy.deepcopy(master_doc)
    for sec in doc["sections"]:
        if _kind(sec) == "skills":
            kept = [l for l in sec["lines"] if l["id"] not in plan["skills_drop"]]
            if len(kept) >= 2:
                sec["lines"] = kept
    # Off-target entries are left out altogether, provided what remains still fills the page.
    trimmed = copy.deepcopy(doc)
    for sec in trimmed["sections"]:
        sec["entries"] = [e for e in sec["entries"] if plan["tiers"].get(e["id"]) != "off_target"]
    trimmed["sections"] = [sec for sec in trimmed["sections"] if sec["entries"] or sec["lines"]]
    if build_resume_pdf(io.BytesIO(), render(trimmed), compact=True) > 1:
        doc = trimmed
    tall = (letter[0], letter[1] * PRETAILOR_PAGES)
    while build_resume_pdf(io.BytesIO(), render(doc), compact=True, pagesize=tall) > 1:
        if not drop_lowest(doc, plan):
            break
    return doc


def read_tailored(text, selection, master):
    """The model's reworded body -> a structure with ids again. Headers and positions lines come
    from the selection (the master's own wording), ground_resume runs as before, and a bullet
    that can't be traced to a master bullet is dropped."""
    heads = {ent["id"]: ent["head"] for sec in selection["sections"] for ent in sec["entries"] if ent["id"]}
    source = {l["id"]: l["text"][2:].strip() for sec in selection["sections"]
              for ent in sec["entries"] for l in _bullets(ent)}

    def entry_id(head):
        m = TAG.search(head)
        if m and m.group(1) in heads:
            return m.group(1)
        toks = _header_tokens(TAG.sub("", head))
        best, best_score = None, 0.0
        for eid, h in heads.items():
            ht = _header_tokens(h)
            score = len(toks & ht) / max(len(toks | ht), 1)
            if score > best_score:
                best, best_score = eid, score
        return best if best_score >= 0.5 else None

    doc = parse_resume(text)
    tagged = {}
    for sec in doc["sections"]:
        for ent in sec["entries"]:
            eid = entry_id(ent["head"])
            ent["head"] = heads.get(eid, TAG.sub("", ent["head"]))
            for line in ent["lines"]:
                m = TAG.search(line["text"])
                line["text"] = TAG.sub("", line["text"])
                if m and m.group(1) in source:
                    tagged[line["text"][2:].strip()] = m.group(1)
    grounded, _ = ground_resume(render(doc), master)

    by_source = {v: k for k, v in source.items()}
    head_ids = {v: k for k, v in heads.items()}

    def bullet_id(body):
        if body in tagged or body in by_source:  # as the model wrote it, or restored from the master
            return tagged.get(body) or by_source[body]
        for was, bid in tagged.items():          # ground_resume trimmed a filler tail
            if was.startswith(body.rstrip(".")):
                return bid
        toks = _content_tokens(body)             # the model dropped the tag
        best, best_score = None, 0.0
        for bid, src in source.items():
            score = len(toks & _content_tokens(src)) / max(len(toks), 1)
            if score > best_score:
                best, best_score = bid, score
        return best if best_score >= 0.6 else None

    out, untraced = {}, []
    for sec in parse_resume(grounded)["sections"]:
        for ent in sec["entries"]:
            eid = head_ids.get(ent["head"])
            if not eid:
                untraced.append(ent["head"][4:])
                continue
            lines = []
            for line in ent["lines"]:
                if not _is_bullet(line["text"]) or _is_positions_line(line["text"]):
                    continue
                line["id"] = bullet_id(line["text"][2:].strip())
                if line["id"]:
                    lines.append(line)
                else:
                    untraced.append(line["text"][2:])
            out[eid] = lines
    if untraced:
        print(f"      [~] Dropped {len(untraced)} line(s) that could not be traced to the selected "
              f"master bullets: " + " / ".join(t[:60] for t in untraced))
    return out


def assemble_resume(selection, tailored, contact):
    """Name, contact line, Education and Skills from the master; every other entry in master
    order with the model's bullets where it returned any, the master's own otherwise."""
    final = {"top": [selection["top"][0], contact] if selection["top"] else [contact], "sections": []}
    for sec in selection["sections"]:
        sec = copy.deepcopy(sec)
        for ent in sec["entries"]:
            if tailored.get(ent["id"]):
                fixed = [l for l in ent["lines"] if not l["id"]]
                ent["lines"] = fixed + tailored[ent["id"]]
        final["sections"].append(sec)
    return final


def fit_resume_to_one_page(path, doc, plan):
    """Writes the resume PDF. Normal layout first, then compact; while it still runs over, the
    lowest-ranked bullet is removed and it is measured again. No model in the loop, so it always
    ends. Returns (pages, [what was removed])."""
    def pages(compact):
        return build_resume_pdf(io.BytesIO(), render(doc), compact=compact)

    removed = []
    if pages(False) > 1:
        while pages(True) > 1:
            gone = drop_lowest(doc, plan)
            if gone is None:
                break
            removed.append(gone)
    final = build_resume_pdf(path, render(doc), compact=pages(False) > 1)
    if removed:
        print(f"      [~] Removed {len(removed)} lowest-ranked line(s) to fit one page.")
    if final > 1:
        print(f"      [!] Resume is still {final} pages: {os.path.basename(path)} -- trim by hand.")
    return final, removed


# ==========================================
# 3e. THE LETTER ANSWERS WHAT THE POSTING ASKS
# ==========================================
def letter_requirements(asks, notes):
    """Prompt lines for the things the posting tells applicants to state. A location preference
    comes from the config. A practice or team preference is chosen by the model, but only from
    the options the posting itself lists."""
    items = asks["letter_asks"]
    if not items:
        return ""
    location = (_facts.get("location") or "").strip()
    city = location.split(",")[0].strip() or "the candidate's city"
    kinds = {a.get("kind") for a in items}
    lines = ["- THE POSTING TELLS APPLICANTS WHAT TO STATE. Answer every item below explicitly,",
             "      each in a plain sentence a reader could point to:"]
    lines += [f'      {i}. {a["ask"]} (posting: "{a["quote"]}")' for i, a in enumerate(items, 1)]
    if "location" in kinds and location:
        lines.append(f"      Location preference: the candidate is based in {location} and prefers {city}.")
    if "practice_or_team" in kinds:
        options = asks["named_options"]
        if options:
            listed = "; ".join(o["name"] + (f' ({", ".join(o["locations"])})' if o["locations"] else "")
                               for o in options)
            lines.append(
                f"      Practice or team preference: name one or two of the ones the posting lists -- "
                f"{listed}. Where locations are listed, choose only among those hiring in {city}. "
                f"Pick what the resume's work best supports and give the reason in one clause drawn "
                f"from the resume. Interest is not experience: never claim past work in that field.")
        else:
            notes.append("Posting asks for a practice or team preference but lists none to choose "
                         "from; add yours to the letter by hand.")
    return "\n    ".join(lines)


def answered_asks(client, letter_text, items):
    """For each ask, the sentence of the letter that answers it ("" if none). A sentence only
    counts if it is really in the letter. Returns None when the check itself failed."""
    prompt = f"""For each numbered item, copy word for word the ONE sentence of the letter that
    explicitly answers it, or "" if no sentence does. Naming the topic without stating the
    preference or answer does not count. Return JSON: [{{"item": 1, "sentence": "..."}}]

    Items:
    {chr(10).join(f"    {i}. {a['ask']}" for i, a in enumerate(items, 1))}

    Letter:
    {letter_text}"""
    try:
        raw = call_json(client, prompt)
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(raw, list):
        return None
    letter_norm = _norm_quote(letter_text)
    found = [""] * len(items)
    for r in raw:
        if isinstance(r, dict) and isinstance(r.get("item"), int) and 1 <= r["item"] <= len(items):
            sentence = str(r.get("sentence") or "")
            if _norm_quote(sentence) and _norm_quote(sentence) in letter_norm:
                found[r["item"] - 1] = sentence
    return found


def enforce_letter_asks(client, letter_text, asks, requirements, master, notes):
    """Checks the letter against the posting's asks, revises once if one is unanswered, and
    reports what is still missing and which practice the model stated on the candidate's behalf."""
    items = asks["letter_asks"]
    if not items:
        return letter_text
    found = answered_asks(client, letter_text, items)
    if found is not None and not all(found):
        missing = [a["ask"] for a, s in zip(items, found) if not s]
        prompt = f"""This cover letter leaves out something the posting tells applicants to state.
        Revise it so it does, changing as little else as possible. Every claim must be traceable
        to the resume. Keep "Dear Hiring Team," and the "Sincerely," sign-off. Output ONLY the letter.

        Not yet answered:
        {chr(10).join("        - " + m for m in missing)}

        {requirements}

        Resume:
        {master}

        Letter:
        {letter_text}"""
        res = client.models.generate_content(
            model='gemini-2.5-flash', contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2))
        revised = scrub_letter(clean_llm_artifacts(res.text or "").strip())
        if revised:
            letter_text = revised
            found = answered_asks(client, letter_text, items)
    if found is None:
        notes.append("Could not confirm the letter answers what the posting asks applicants to state: "
                     + "; ".join(a["ask"] for a in items) + ".")
        return letter_text
    for a, sentence in zip(items, found):
        if not sentence:
            notes.append(f"Letter does not answer what the posting asks: {a['ask']}. Add it by hand.")
        elif a.get("kind") == "practice_or_team":
            chosen = [o["name"] for o in asks["named_options"]
                      if _norm_quote(o["name"]) in _norm_quote(sentence)]
            notes.append("Letter states a practice preference chosen by the model from the posting's "
                         f"list ({', '.join(chosen) or 'see the letter'}); change it if it is not yours.")
    return letter_text


# ==========================================
# 4. ONE APPLICATION PACKAGE
# ==========================================
def build_package(client, job, label, output_dir, resume_text, notes=None):
    """Builds the four PDFs (plus any extra-steps note) for one job. Returns True on success.
    notes collects what the reader must check before sending; it ends up in the report."""
    notes = notes if notes is not None else []
    # The deep scrape lives in full_description. raw_text is only the 5-line preview card.
    raw_jd = job.get("full_description") or ""

    # Never generate documents from an empty or stub description.
    if len(raw_jd) < 500:
        print(f"   [!] SKIPPED {job.get('url', 'unknown URL')} -- description is only "
              f"{len(raw_jd)} chars. Deep scrape likely failed for this URL.")
        notes.append(f"No package: the description is only {len(raw_jd)} characters.")
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

    master_doc = number_master(parse_resume(resume_text))

    max_retries = 5
    for attempt in range(max_retries):
        del notes[:]
        try:
            if looks_truncated(raw_jd):
                print("      [!] Description is cut off behind Handshake's \"More\" button.")
                notes.append("The scraped description is cut off behind Handshake's \"More\" button; these "
                             "documents were written from its first lines only. Read the full posting.")
            asks = read_posting_asks(client, raw_jd)
            if asks is None:
                asks = dict(NO_ASKS)
                notes.append("Could not read the posting for application instructions; check it for "
                             "contact details or statements it asks for.")
            plan = plan_selection(client, raw_jd, asks, master_doc)
            if not plan["ranked"]:
                notes.append("Resume content could not be ranked for this role; it was cut from the "
                             "bottom of the master resume instead.")
            selection = select_for_tailoring(master_doc, plan)
            requirements = letter_requirements(asks, notes)
            chosen = {ent["id"] for sec in selection["sections"] for ent in sec["entries"]}
            left_out = [ent["head"][4:].split(" | ")[0] for sec in master_doc["sections"]
                        for ent in sec["entries"] if ent["id"] and ent["id"] not in chosen]
            letter_focus = ("- Build the letter on the experience selected for the resume above. These were "
                            "left off the resume for this role, so do not lean on them: "
                            + "; ".join(left_out) + "." if left_out else "")

            prompt = f"""
    You are an elite executive career coach and ATS optimization expert. Read this raw job data and candidate master resume.
    Raw Job Data: {raw_jd}
    Master Kitchen-Sink Resume: {resume_text}

    TASK REQUIREMENTS:
    Output EXACTLY three parts separated by '|||'.
    CRITICAL: Do NOT output conversational filler. Start immediately with the requested text.

    PART 1: Extract ONLY the official, clean company name from the raw job data.
    |||
    PART 2: The TAILORED RESUME BODY for this {asks["role_type"] or "role"} position.
    The entries and bullets below were already selected for this job. The name, contact line,
    Education and Skills are added afterwards: do NOT write them.

    SELECTED ENTRIES:
    {render(selection, tags=True, kinds=("entries", "leadership"))}

    - Output every ## section and every ### entry above, in the SAME ORDER. Copy each ### header
      line exactly, including its [E#] tag.
    - Every bullet keeps its [B#] tag at the start. One output bullet per input bullet: never
      merge, split, add, or move a bullet to another entry. Lines without a tag are copied as is.
    - WITHIN an entry, you MAY reorder its bullets so the most relevant come first, and REFRAME
      them so the language echoes the job description where it HONESTLY applies.
    - TIGHTEN: aim for two lines (about 230 characters) per bullet where that loses no number,
      named tool, named organisation or named method.

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
    - FORMAT: You must strictly use the exact Markdown tags provided (## SECTIONS, ### Roles | Dates, - bullets). Do not break this formatting.
    |||
    PART 3: Write a confident, direct 3-paragraph cover letter ready to send.
    - The SAME GROUNDING RULE applies. Every skill, course, and experience you cite must
      appear in the master resume. Do not claim knowledge of a technique the resume does not
      evidence, and do not manufacture enthusiasm for an industry the candidate has no
      stated connection to.
    - Write about what the candidate HAS done and why it transfers. Do not assert domain
      expertise they lack; where a gap is obvious, show transferable reasoning instead of
      papering over it.
    - Lead with the experience that fits this {asks["role_type"] or "role"} work, not with the
      most technical project.
    - Describe each experience as what it was. Never relabel it as the posting's field: scoring
      sales leads is not "economic and financial analysis".
    - Open with "Dear Hiring Team,". Do not say where the posting was found ("as advertised
      on LinkedIn") -- you do not know.
    - Do not quote the posting's phrases back in quotation marks, and do not grade the fit
      yourself ("align perfectly", "precisely the type of candidate you are seeking").
    {letter_focus}
    {requirements}
    {availability_rule}
    - End with "Sincerely," on its own line, then the candidate's name. Do not add a
      postscript or any commentary after the signature.
    """

            res = client.models.generate_content(
                model='gemini-2.5-flash', contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            parts = res.text.split('|||')

            company = clean_llm_artifacts(parts[0]).strip() if len(parts) > 0 else f"Company_{label}"
            tailored = read_tailored(clean_llm_artifacts(parts[1]).strip(), selection, resume_text) if len(parts) > 1 else {}
            if not tailored:
                notes.append("The tailored resume could not be read; the resume uses the master wording.")
            master_contact = selection["top"][1] if len(selection["top"]) > 1 else ""
            full_resume = assemble_resume(selection, tailored, contact_line(master_contact, asks, notes))
            invented = unsourced_numbers(render(full_resume), resume_text)
            if invented:
                notes.append(f"Resume has numbers that are not in the master resume: {', '.join(invented)}.")
            letter_text = clean_llm_artifacts(parts[2]).strip() if len(parts) > 2 else res.text
            letter_text = scrub_letter(letter_text)
            letter_text = enforce_letter_asks(client, letter_text, asks, requirements, resume_text, notes)

            clean_comp = re.sub(r'[^\w\s-]', '', company).strip().replace(' ', '_')
            stem = os.path.join(output_dir, f"{label}_{clean_comp}")

            # 1 & 2. Resume & Cover Letter
            pages, removed = fit_resume_to_one_page(f"{stem}_Full_Resume.pdf", full_resume, plan)
            if pages > 1:
                notes.append(f"Resume is {pages} pages even with every optional line removed; trim it by hand.")
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
                notes.append(f"Posting asks for more than a resume and letter; see {os.path.basename(extra_path)}.")

            for n in notes:
                print(f"      [note] {n}")
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
                notes.append(f"No package: {e}")
                return False
    notes.append("No package: the model was unavailable after several attempts.")
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


def append_package_notes(package_notes, report="FINAL_STRATEGY.md"):
    """Adds what must be checked before sending to the report. The report is written before the
    packages and emailed after them, so this is the one place a package problem can be seen
    without opening the CI log."""
    if not package_notes or not os.path.exists(report):
        return
    lines = ["\n\n---\n\n## Package notes\n", "_Check these before sending._\n"]
    for heading, notes in package_notes:
        lines += [f"- **{heading}:** {note}" for note in notes]
    with open(report, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


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

    built, package_notes = 0, []
    for label, job in labelled:
        notes = []
        ok = build_package(client, job, label, output_dir, resume_text, notes)
        if notes:
            package_notes.append((f"{label}: {job.get('title') or 'Unknown role'}, "
                                  f"{job.get('company') or 'unknown company'}", notes))
        if ok:
            built += 1
            if on_request and job.get("url"):
                # Packaged means never resurfaced -- same as an approved job.
                from database_manager import init_db, mark_job_packaged
                init_db()
                mark_job_packaged(job["url"])
    if not on_request:
        append_package_notes(package_notes)
    print(f"Done: {built} of {len(labelled)} package(s) written to {output_dir}/")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--near-miss" in args:
        build_application_packages(near_miss_requests=args[args.index("--near-miss") + 1:])
    else:
        build_application_packages()