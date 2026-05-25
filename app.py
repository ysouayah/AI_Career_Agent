import streamlit as st
import os
import subprocess

# --- UI CONFIGURATION ---
st.set_page_config(page_title="AI Career Agent", page_icon="🎯", layout="wide")
st.title("🤖 AI Career Agent: Executive Dashboard")
st.markdown("Upload your context, enter your keys, and let the AI find your Unicorn roles.")

# --- SIDEBAR: SECRETS & CONFIG ---
st.sidebar.header("🔑 System Credentials")

# Pull from secrets.toml if it exists, otherwise leave blank
gemini_key = st.sidebar.text_input("Gemini API Key", type="password", value=st.secrets.get("GEMINI_API_KEY", ""))
email_user = st.sidebar.text_input("Gmail Address", value=st.secrets.get("EMAIL_USER", ""))
email_pass = st.sidebar.text_input("Gmail App Password", type="password", value=st.secrets.get("EMAIL_PASS", ""))

# --- MAIN DASHBOARD: FILE UPLOADS ---
st.header("📄 Candidate Profile")
col1, col2 = st.columns(2)

with col1:
    resume_file = st.file_uploader("Upload Master Resume (PDF)", type=["pdf"])
with col2:
    transcript_file = st.file_uploader("Upload Transcript (Optional)", type=["pdf"])

st.markdown("---")

# --- EXECUTION LOGIC ---
if st.button("🚀 Launch AI Pipeline", use_container_width=True):
    
    # 1. Validation Checks
    if not gemini_key:
        st.error("⚠️ Please enter your Gemini API Key in the sidebar.")
        st.stop()
    if not resume_file:
        st.error("⚠️ A Master Resume is required to run the pipeline.")
        st.stop()

    # 2. Save Uploaded Files to the Root Folder
    # This automatically overwrites the old ones so the agent always uses fresh data
    with open("resume.pdf", "wb") as f:
        f.write(resume_file.getbuffer())
        
    if transcript_file:
        with open("transcript.pdf", "wb") as f:
            f.write(transcript_file.getbuffer())
    elif os.path.exists("transcript.pdf"):
        # If they didn't upload a new one, delete the old one so it doesn't cross-contaminate
        os.remove("transcript.pdf")

    # 3. Inject Credentials into the System Environment
    os.environ["GEMINI_API_KEY"] = gemini_key
    if email_user and email_pass:
        os.environ["EMAIL_USER"] = email_user
        os.environ["EMAIL_PASS"] = email_pass
    else:
        st.warning("No email credentials provided. The final report will not be emailed.")

    # 4. Run the Pipeline
    status_msg = st.empty() # Create a temporary container
    status_msg.info("Initializing Agent Sub-Processes. Please wait...")
    with st.spinner('Deploying Extraction Fleet & AI Sifters... This may take a few minutes.'):
        try:
            result = subprocess.run(["python3", "run_everything.py"], capture_output=True, text=True)
            status_msg.empty() # Wipe the blue info box off the screen!
            if result.returncode == 0:
                st.success("✅ Pipeline Complete!")
                
                # 5. Display the Results in the UI
                if os.path.exists("FINAL_STRATEGY.md"):
                    with open("FINAL_STRATEGY.md", "r") as f:
                        report_text = f.read()
                    
                    # Display the markdown nicely in an expander or container
                    with st.container(border=True):
                        st.markdown(report_text)
                else:
                    st.error("Pipeline finished, but FINAL_STRATEGY.md was not found.")
            else:
                st.error("❌ The pipeline crashed.")
                st.expander("Show Error Logs").text(result.stderr)
                
        except Exception as e:
            st.error(f"Failed to start pipeline: {e}")