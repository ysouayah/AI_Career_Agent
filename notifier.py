import smtplib
from email.message import EmailMessage
import os

def send_strategy_report(recipient_email):
    report_path = "FINAL_STRATEGY.md"
    
    if not os.path.exists(report_path):
        print("No report found to send.")
        return

    with open(report_path, "r") as f:
        report_content = f.read()

    # Create the email container
    msg = EmailMessage()
    msg.set_content(report_content)
    msg["Subject"] = "🎯 Weekly AI Job Strategy: High-Probability Matches"
    
    # These pull securely from the terminal environment we set up!
    sender_email = os.environ.get("EMAIL_USER")
    sender_password = os.environ.get("EMAIL_PASS")
    
    msg["From"] = sender_email
    msg["To"] = recipient_email

    try:
        # Standard Gmail SMTP settings
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender_email, sender_password)
            smtp.send_message(msg)
        print("Report successfully emailed!")
    except Exception as e:
        print(f"Failed to send email: {e}")