from google import genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os
import json
import base64

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service():
    """Handles headless/interactive OAuth authentication for Gmail."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def scan_inbox():
    print("--- INITIATING INBOX SCANNER & APPLICATION TRACKER ---")
    
    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"ERROR: Failed to authenticate with Gmail API: {e}")
        return

    # Load active jobs to cross-reference sender domains or company names
    try:
        with open("sifted_jobs.json", "r") as f:
            jobs = json.load(f)
    except FileNotFoundError:
        print("No active sifted_jobs.json found to track.")
        return

    # Fetch the last 15 messages from your inbox
    results = service.users().messages().list(userId='me', maxResults=15).execute()
    messages = results.get('messages', [])

    if not messages:
        print("No recent messages found.")
        return

    print(f"Scanning {len(messages)} recent emails for recruiter updates...")
    
    import tomllib
    
    # Load the Gemini API key from your secrets.toml file
    # Locate and load the Gemini API key
    api_key = None
    possible_paths = ["secrets.toml", ".streamlit/secrets.toml"]
    
    for path in possible_paths:
        import os
        if os.path.exists(path):
            with open(path, "rb") as f:
                secrets = tomllib.load(f)
                # Check for common key names
                if "GEMINI_API_KEY" in secrets:
                    api_key = secrets["GEMINI_API_KEY"]
                    break
                elif "api_key" in secrets:
                    api_key = secrets["api_key"]
                    break

    if not api_key:
        print("CRITICAL ERROR: Could not find GEMINI_API_KEY in any secrets.toml file.")
        print("Please check that your key is named exactly 'GEMINI_API_KEY = \"your_key\"' in the file.")
        return

    client = genai.Client(api_key=api_key)
    
    for msg in messages:
        msg_id = msg['id']
        txt = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        headers = txt.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
        
        snippet = txt.get('snippet', '')
        
        # Use Gemini to classify the email context
        prompt = f"""
        You are an elite career agent assistant. Analyze this incoming email to see if it relates to a job application status update.
        
        Sender: {sender}
        Subject: {subject}
        Body Snippet: {snippet}
        
        Task: Classify this email into ONE of these exact categories:
        1. "INTERVIEW" (Recruiter requesting an interview, screening, or scheduling a call)
        2. "REJECTION" (Automated or manual rejection notice)
        3. "UPDATE" (Next steps, request for more info, or general application movement)
        4. "IRRELEVANT" (Newsletter, marketing, spam, or personal email)
        
        Output format: CATEGORY || Brief 1-sentence summary of what they said.
        """
        
        try:
            res = client.models.generate_content(
                model='gemini-2.5-flash', contents=prompt
            )
            classification = res.text.strip()
            
            if "IRRELEVANT" not in classification:
                print(f"\n[ALERT] Found Job Update!")
                print(f"   From: {sender}")
                print(f"   Subject: {subject}")
                print(f"   Analysis: {classification}")
                
        except Exception as e:
            continue

if __name__ == '__main__':
    scan_inbox()