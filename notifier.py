import os
import smtplib
import tomllib
import markdown
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

def send_strategy_report(recipient_email):
    print("\n--- [NOTIFIER] Waking up Executive Mailer ---")

    # Fetch credentials from environment or secrets.toml
    sender_email = os.environ.get("EMAIL_USER")
    app_password = os.environ.get("EMAIL_PASS")
    
    if not sender_email or not app_password:
        secrets_path = os.path.join(".streamlit", "secrets.toml")
        with open(secrets_path, "rb") as f: secrets = tomllib.load(f)
        sender_email = secrets.get("EMAIL_USER")
        app_password = secrets.get("EMAIL_PASS")

    if not os.path.exists("FINAL_STRATEGY.md"): 
        print("[!] FINAL_STRATEGY.md missing.")
        return
        
    with open("FINAL_STRATEGY.md", "r", encoding="utf-8") as f: raw_md = f.read()
    if not raw_md.strip(): return

    # --- THE GUILLOTINE ---
    # Forcefully slice off everything starting from the packages section 
    cutoff_markers = [
        "==================================================",
        "📦 READY-TO-SEND APPLICATION PACKAGES",
        "READY-TO-SEND APPLICATION PACKAGES"
    ]
    
    for marker in cutoff_markers:
        if marker in raw_md:
            raw_md = raw_md.split(marker)[0].strip()
    # ----------------------

    # Convert Markdown to HTML
    html_content = markdown.markdown(raw_md, extensions=['tables'])

    # Inject CSS Styling to mimic Streamlit UI
    styled_email = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F8FAFC; color: #1E293B; padding: 20px; line-height: 1.6; }}
            .container {{ max-width: 680px; margin: 0 auto; background: #FFFFFF; padding: 32px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); border: 1px solid #E2E8F0; }}
            h1 {{ color: #0F172A; font-size: 22px; border-bottom: 2px solid #3B82F6; padding-bottom: 10px; margin-top: 0; }}
            h2 {{ color: #1E293B; font-size: 18px; margin-top: 28px; background-color: #F1F5F9; padding: 10px 14px; border-radius: 6px; border-left: 4px solid #3B82F6; }}
            h3 {{ color: #334155; font-size: 15px; margin-top: 20px; }}
            a {{ color: #2563EB; text-decoration: none; font-weight: 600; }}
            a:hover {{ text-decoration: underline; }}
            ul {{ padding-left: 20px; }}
            li {{ margin-bottom: 6px; }}
            .footer {{ font-size: 12px; color: #64748B; text-align: center; margin-top: 30px; }}
        </style>
    </head>
    <body>
        <div class="container">
            {html_content}
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = sender_email, recipient_email, "🎯 AI Career Agent: Executive Match Report & Packages"
    msg.attach(MIMEText(styled_email, 'html', 'utf-8'))

    # Attach all generated PDFs
    pdf_dir = "application_packages"
    if os.path.exists(pdf_dir):
        for file in sorted(os.listdir(pdf_dir)):
            if file.endswith(".pdf"):
                file_path = os.path.join(pdf_dir, file)
                with open(file_path, "rb") as f:
                    part = MIMEApplication(f.read(), _subtype="pdf")
                    part.add_header('Content-Disposition', 'attachment', filename=file)
                    msg.attach(part)
                print(f"[+] Attached: {file}")

    print("[*] Transmitting VIP package over Port 465...")
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender_email, app_password)
        server.send_message(msg)
    print(f"\n🎉 VIP Report & PDFs successfully delivered to {recipient_email}\n")

if __name__ == "__main__":
    # Allows you to test it directly from the terminal without running the whole pipeline
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    with open(secrets_path, "rb") as f: secrets = tomllib.load(f)
    send_strategy_report(secrets.get("EMAIL_USER"))