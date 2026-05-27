# 🤖 AI Career Agent Pipeline

An automated, end-to-end Python pipeline that acts as a personalized AI recruiter. This agent runs locally to bypass enterprise bot-mitigation, scrapes live job boards, filters out irrelevant listings using a Large Language Model (Gemini), grades the remaining roles against your custom "Unicorn Candidate" rubric, and securely emails a formatted strategy report of the best matches.

## ⚙️ How It Works
1. **The Brainstormer:** Dynamically reads your resume and generates highly specific search queries tailored to your background.
2. **The Extractors:** Uses Playwright to run headless, stealth web scraping across platforms (currently supports Handshake, Indeed, and LinkedIn).
3. **The Sifter (Gemini 2.5 Flash):** Analyzes raw job descriptions against your specific academic and professional profile by reading your `resume.pdf` in memory.
4. **The Grader:** Scores the filtered jobs on a 0-100 rubric strictly enforcing the dealbreakers, experience ceilings, and industry targets you provide in your custom preferences.

## 🚀 How to Run Locally

### Prerequisites
* **Python 3.8+**
* A **Gemini API Key** (Free from Google AI Studio)
* A **Gmail App Password** (If you want the pipeline to automatically email you the final reports) <-- Not yet functional, leave as is.

### 1. Install Dependencies
Ensure you have Python installed, then run:
`pip install google-generativeai pdfplumber playwright playwright-stealth streamlit`

*Crucial Step:* You must install the Playwright browser binaries, or the extractors will fail:
`playwright install`

### 2. Launch the Agent (Two Methods)

**Method A: The Interactive Web Dashboard (Recommended)**
You can run the agent entirely through a local, visually interactive dashboard. 
Run this command in your terminal:
`streamlit run app.py`

A web app will open in your browser. Enter your system credentials in the sidebar, upload your `resume.pdf`, type your custom dealbreakers into the text box, and hit Launch.

**Method B: The Command Line (Headless Orchestrator)**
If you prefer to run the pipeline strictly through the terminal without the UI, ensure your `resume.pdf` and `preferences.txt` are placed in the root folder. 

Set your environment variables in your terminal before running:
`export GEMINI_API_KEY="your_api_key_here"`
`export EMAIL_USER="your_email@gmail.com"`
`export EMAIL_PASS="your_16_letter_app_password"`

Run the orchestrator:
`python3 run_everything.py`

*Note: You may need to run `python3 handshake_auth.py` first to generate a fresh `handshake_state.json` session cookie if the university scraper times out.*

## ⚠️ Disclaimer
This project uses automated web scraping. Platforms like LinkedIn and Indeed frequently update their DOM structures and bot-mitigation strategies. This tool is intended for educational, personal research, and portfolio demonstration purposes. Please review the Terms of Service of any platform you scrape and use this tool responsibly.
