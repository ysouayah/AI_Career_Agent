# 🤖 AI Career Agent Pipeline

An automated, end-to-end Python pipeline that acts as a personalized AI recruiter. This agent bypasses enterprise bot-mitigation, scrapes live job boards, filters out irrelevant listings using a Large Language Model (Gemini), grades the remaining roles against a custom "Unicorn Candidate" rubric, and emails a formatted strategy report of the best matches.

## ⚙️ How It Works
1. **The Brainstormer:** Generates highly specific search queries based on target industries.
2. **The Extractors:** Uses Playwright to run headless, stealth web scraping across platforms (currently supports Handshake, Indeed, and LinkedIn).
3. **The Sifter (Gemini 2.5 Flash):** Analyzes raw job descriptions against the user's specific academic and professional profile by dynamically reading their provided `resume.pdf` and other provided documents.
4. **The Grader:** Scores the filtered jobs on a 0-100 rubric, looking for specific intersections of AI, policy, ethics, and geopolitical data.

## 🚀 How to Run Locally

**1. Install Dependencies**
Ensure you have Python 3 installed, then run:
`pip install google-generativeai pdfplumber playwright playwright-stealth streamlit`

*Crucial Step:* You must install the Playwright browser binaries, or the extractors will fail:
`playwright install`

**2. Launch the Agent (Two Methods)**

**Method A: The Interactive Web Dashboard (Recommended)**
You can run the agent entirely through a local, visually interactive dashboard. 
Run this command in your terminal:
`streamlit run app.py`

A web app will open in your browser. Simply upload your `resume.pdf`, type your dealbreakers into the text box, and hit Launch.

**Method B: The Command Line (Headless Orchestrator)**
If you prefer to run the pipeline strictly through the terminal without the UI, ensure your `resume.pdf` and `preferences.txt` are placed in the root folder. 

Set your environment variables in your terminal before running:
`export GEMINI_API_KEY="your_api_key_here"`
`export EMAIL_USER="your_email@gmail.com"`
`export EMAIL_PASS="your_16_letter_app_password"`

Run the orchestrator:
`python3 run_everything.py`

*Note: You may need to run `python3 handshake_auth.py` first to generate a fresh `handshake_state.json` session cookie if the scraper times out.*
