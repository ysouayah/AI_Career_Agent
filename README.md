# 🤖 AI Career Agent Pipeline

An automated, end-to-end Python pipeline that acts as a personalized AI recruiter. This agent scrapes live job boards, filters out irrelevant listings using a Large Language Model (Gemini), grades the remaining roles against a custom "Unicorn Candidate" rubric, and emails a formatted strategy report of the best matches.

## ⚙️ How It Works
1. **The Brainstormer:** Generates highly specific search queries based on target industries.
2. **The Extractors:** Uses Playwright to run headless, stealth web scraping across platforms (currently supports Handshake, Indeed, and LinkedIn).
3. **The Sifter (Gemini 2.5 Flash):** Analyzes raw job descriptions against the user's specific academic and professional profile by dynamically reading their provided `resume.pdf` and other provided documents.
4. **The Grader:** Scores the filtered jobs on a 1-100 rubric, looking for specific intersections of AI, policy, ethics, and geopolitical data.
5. **The Notifier:** Automatically compiles the top results into a Markdown strategy report and securely emails it to the user.

## 🚀 How to Run Locally

**1. Install Dependencies**
Ensure you have Python 3 installed, then run:
`pip install google-generativeai pdfplumber playwright playwright-stealth`

**2. Environment Variables Setup**
This script requires a Gemini API key and a Google App Password for the email notifier. Set these in your terminal before running:
`export GEMINI_API_KEY="your_api_key_here"`
`export EMAIL_USER="your_email@gmail.com"`
`export EMAIL_PASS="your_16_letter_app_password"`

**3. Run the Orchestrator**
`python3 run_everything.py`

*Note: You may need to run `python3 handshake_auth.py` first to generate a fresh `handshake_state.json` session cookie if the scraper times out.*
