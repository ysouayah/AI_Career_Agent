# YOUSSEF SOUAYAH
ysouayah@bu.edu | linkedin.com/in/ysfsouayah | github.com/ysouayah

## EDUCATION

### Boston University, Kilachand Honors College, Boston, MA | Expected May 2027
- Dual Degree, B.A. Political Science & B.S. Data Science | GPA: 3.58 | Dean's List
- **Relevant Coursework:** Introduction to Machine Learning & AI; Applied Statistics; Algorithms for Data Science; Data Mechanics; Foundations of Data Science I–III; Data Science for Politics; Data, Society & AI Ethics; Spark! ML X-Lab Practicum, Machine Learning for Business Analytics, Business Experiments & Methods (in progress)

## TECHNICAL SKILLS

- **Languages & Tools:** Python (Pandas, NumPy), SQL, PostgreSQL, R, Tableau, Plotly, Streamlit, Git
- **AI & Data Engineering:** LLM orchestration (Gemini API), Retrieval-Augmented Generation (RAG), prompt engineering, Playwright browser automation, ETL pipeline design, GitHub Actions
- **Productivity Tools:** Microsoft Office Suite, Google Workspace
- **Spoken Languages:** Native fluency in English and Arabic; full professional fluency in French
- **Certifications:** CITI Program Certification: Human Subjects Protection Training – Social & Behavioral Focus, Boston University (Charles River Campus) | Record ID: 77467029 | Completed June 3, 2026 (Expires June 3, 2029)

## PROFESSIONAL EXPERIENCE

### BU Spark!, Boston University — Special Initiatives Intern | September 2026 – Present
- Scope, draft, and audit technical Project Descriptions defining deliverables, data requirements, and success criteria for client-sponsored machine learning and data science practicum teams (CDS DS 549/701, Justice Media Co-Lab).
- Translate external partner problem statements into engineering-ready specifications that serve as the working contract between student engineering teams, faculty, and clients across multi-semester engagements.

### Department of Political Science, Boston University, Boston, MA — Research Assistant to Estelle Brun (PhD Candidate) | Summer 2026
- **Qualitative Data Processing:** Transcribed, formatted, and processed semi-structured French audio interviews with elected officials and cultural bureaucrats across Southeastern France (PACA) for a comparative political science dissertation.
- **Thematic Networks Analysis:** Applied Attride-Stirling's (2001) and Downing & Brun's (2021) qualitative methodologies to categorize raw text into thematic networks, analyzing memory politics, institutional identity, and right-wing populism.
- **Interpretivist Analysis:** Utilized interpretivist ethnography (Wedeen, 2010) to code non-verbal behavioral cues, vocal shifts, and evasions, evaluating how local actors construct place-based resentment (Cramer, 2016), nativist boundaries (Pirro, 2023), and historical narratives (Roman National, colonial, and Confederate memory).
- **IRB & Compliance:** Adhered strictly to IRB Protocol 8264X guidelines for human subject research, preserving participant anonymity and securing sensitive qualitative data in encrypted institutional repositories.

### WildyNess — Growth & Automation Intern (Remote) | Summer 2026
- Engineered a custom AI discovery agent to automate B2B partner acquisition, building multi-threaded web scraping pipelines (via Apify and ZenRows) to identify, qualify, and classify North American and European tour operators as prospective partners for Tunisia-based travel offerings.
- Built and ran a B2B email outreach campaign on Apollo covering list building, email verification through data enrichment, and paced daily send volumes to protect sender reputation; the campaign generated replies and partnership conversations with target operators.
- Architected an automated lead enrichment workflow integrated with Apollo to profile high-converting contact segments and dynamically generate look-alike partner lists, dramatically increasing outbound pipeline efficiency.
- Designed automated filtering and validation logic to score leads based on regional presence and operational criteria, removing manual qualification bottlenecks for the business development team.
- Developed a targeted creator discovery agent to identify, scrape, and vet international and domestic travel creators; implemented custom filtering logic (content style, commercial models, geographic focus) to deliver qualified outreach lists for marketing collabs.
- Mapped automation opportunities across internal Notion workflows to surface sales performance data for the leadership team.
- Built an automated SEO link-mapping pipeline using Python, LLMs, and stealth browser automation to map 590+ verbatim internal links across 270+ live articles with 99.5% verified accuracy, saving 30+ hours of manual site maintenance.

### Boston Debate League — Data & Policy Analytics Intern | Summer 2026
- Engineered a cross-season data tracking pipeline analyzing multi-year tournament datasets (2024–2026) across 80+ schools to quantify BDL Summer Camp ROI across 4 core dimensions.
- Developed custom data normalization algorithms to resolve historical false positives, accurately mapping student retention, division mobility, and speaker point progression.
- Conducted comparative cohort analyses demonstrating BDL Summer Camp attendees improved speaker points 78% more than non-attendees (+1.51 pts vs. +0.85 pts control group) and drove a +6.3% school-wide win rate advantage.
- Synthesized empirical research into an executive memo for senior leadership, delivering data-backed policy recommendations on scholarship allocation, bridge retention, and program equity.

### Center on Forced Displacement, Boston University — Summer Intern | Summer 2025
- Conducted qualitative interviews, transcribing verbal testimonials into polished, standardized profiles.
- Collected, cleaned, and organized primary-source migration records from diverse global entities into structured datasets for comparative research and statistical analysis.

### Dugree — Political Analyst Intern & Recruitment Lead | Summer 2024
- Reviewed AI-assisted dialogues on sensitive geopolitical conflicts and identified biased or one-sided framing.
- Improved balance and neutrality by adding counterpoints, labeling examples for bias/clarity, and refining how sensitive topics were handled.

## SELECTED DATA & AI PROJECTS

### Autonomous AI Career Agent & Job Fulfillment Pipeline | June 2026 – Present
- Architected a seven-phase autonomous pipeline in Python orchestrating six independent scraper and generator modules via subprocess execution, with a SQLite persistence layer and composite company-plus-title signature hashing to deduplicate ATS location spam across three job boards before any inference spend; deployed on GitHub Actions for scheduled weekly runs.
- Engineered a two-stage LLM evaluation cascade (Gemini 2.5 Flash) that sifts high-volume preview cards into a shortlist, routes survivors through a Playwright deep-scrape for full-length descriptions, then batch-grades all targets in a single call, cutting API token consumption while eliminating a data-desync defect that had caused the generators to hallucinate role titles.
- Designed a deterministic nine-gate veto rubric compiled dynamically from a JSON preference config, hard-zeroing any role that trips explicit years-of-experience minimums, semantic seniority markers ("end-to-end ownership," "production at scale"), off-cohort graduation timelines, non-commutable locations, unmet hard requirements, internships, or predatory staffing and resume-farm operators, then surfacing only matches scoring 85/100 or higher.
- Built a Python-to-PDF fulfillment engine on ReportLab that compiles four upload-ready ATS documents per approved role — a pruned one-page tailored resume, cover letter, 15-question interview prep sheet, and a company brief grounded in live web-search retrieval — hardened with URL-keyed report reconciliation, XML sanitization, and exponential-backoff retry logic against 429/503 rate limits.

### "Pick For Me" Live Market Discovery Agent | July 2026
- Engineered a real-time web scraping pipeline utilizing Python and SerpApi to dynamically extract, clean, and normalize live retail inventory and local business data from Google search results.
- Designed a multi-phase LLM evaluation engine (Gemini 2.5 Flash) to parse unstructured user constraints, combining strict deterministic filtering with an exponentially weighted AI scoring matrix to mathematically rank optimal results.
- Developed a reactive frontend architecture using Streamlit, Pandas, and Plotly Express to visualize score breakdowns and deliver direct vendor purchasing links in a clean, user-friendly UI.

### MENA Immigration Policy RAG Agent | June – September 2025
- Built an AI-assisted research tool using Python and the Google Gemini API to help users navigate complex U.S. immigration policies affecting MENA populations.
- Engineered a PostgreSQL database and retrieval pipeline that searches policy documents by semantic meaning rather than exact keywords, significantly improving the agent's accuracy on conversational questions.
- Designed strict prompt guardrails and a live web-search fallback to prevent AI hallucinations, ensuring the agent prioritizes the most up-to-date policies and provides verifiable source citations for every answer.
- Developed a related Tableau dashboard visualizing historical displacement trends to provide broader context for non-technical stakeholders.

## LEADERSHIP & ACTIVITIES

### Phi Alpha Delta Pre-Law Fraternity, Boston University | 2024 – Present
- *VP of Membership (2026 – Present) · Membership-in-Training (2025 – 2026) · A-Board, CSB Committee (2024 – 2025)*
- Manage the membership database to support accurate records and compliance with national bylaws.

### North African Student Organization, Boston University | 2023 – Present
- *Co-President (2025 – Present) · Secretary (2024 – 2025)*
- Lead student committees in planning, budgeting, and executing large-scale community events.
- Coordinate outreach and volunteer responsibilities to keep events organized and on track.

### Boston Debate League — Volunteer Judge and Alumnus | 2016 – Present
- Research, construct, and evaluate complex arguments regarding public policy and ethics.
- Provide constructive, detailed feedback and qualitative evaluations of debaters' public speaking and argumentation skills.