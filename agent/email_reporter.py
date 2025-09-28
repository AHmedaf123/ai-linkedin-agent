import smtplib, os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from datetime import datetime
import ssl

logger = logging.getLogger("linkedin-agent")

def send_email_report(post, is_error: bool = False, is_draft: bool = False, attachments=None):
    """Send an email report about the LinkedIn post or error.

    Args:
        post (dict): Post data including title, body, seo_score, etc.
        is_error (bool): Whether this is an error report
        is_draft (bool): Whether this is a draft-only mode report
        attachments (list): List of file paths to attach to the email
    """
    try:
        # Addresses and basic credentials (backward compatible)
        sender = os.getenv("EMAIL_USER") or os.getenv("EMAIL_SENDER")
        receiver = os.getenv("EMAIL_RECEIVER") or os.getenv("EMAIL_TO")
        password = os.getenv("EMAIL_PASS") or os.getenv("EMAIL_PASSWORD")

        # Provider-agnostic SMTP settings
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_security = os.getenv("SMTP_SECURITY", "starttls").lower()  # starttls | ssl | none
        smtp_user = os.getenv("SMTP_USER", sender)  # allow distinct auth user
        smtp_pass = os.getenv("SMTP_PASS", password)

        if not sender or not receiver:
            logger.error("Email sender/receiver not configured. Skipping email report.")
            return False

        if (smtp_user and not smtp_pass) or (smtp_pass and not smtp_user):
            logger.error("SMTP credentials incomplete (user/pass mismatch). Skipping email report.")
            return False

        # Build message
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receiver

        title = post.get("title", "No Title")
        seo_score = post.get("seo_score", "N/A")
        seo_keywords = post.get("seo_keywords", [])
        hashtags = post.get("hashtags", [])
        body = post.get("body", "")

        if is_error:
            msg["Subject"] = f"❌ LinkedIn Agent Error: {title}"
            html_content = f"""
            <h2>LinkedIn Agent Error ❌</h2>
            <p><b>Error:</b> {title}</p>
            <p><b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <hr>
            <pre style=\"background-color: #f8f8f8; padding: 10px; border-radius: 5px; white-space: pre-wrap;\">{body}</pre>
            """
        elif is_draft:
            msg["Subject"] = f"📝 LinkedIn Draft Post: {title}"
            html_content = f"""
            <h2>LinkedIn Draft Post 📝</h2>
            <p><b>Title:</b> {title}</p>
            <p><b>SEO Score:</b> {seo_score}%</p>
            <p><b>Keywords:</b> {', '.join(seo_keywords)}</p>
            <p><b>Hashtags:</b> {' '.join(hashtags)}</p>
            <hr>
            <pre style=\"background-color: #f8f8f8; padding: 10px; border-radius: 5px; white-space: pre-wrap;\">{body}</pre>
            <hr>
            <p><a href=\"https://www.linkedin.com/feed/?postCreate=true\" target=\"_blank\">Open LinkedIn Post Creator</a></p>
            """
        else:
            msg["Subject"] = f"✅ LinkedIn Post Published: {title}"
            html_content = f"""
            <h2>LinkedIn Post Successfully Published ✅</h2>
            <p><b>Title:</b> {title}</p>
            <p><b>SEO Score:</b> {seo_score}%</p>
            <p><b>Keywords:</b> {', '.join(seo_keywords)}</p>
            <p><b>Hashtags:</b> {' '.join(hashtags)}</p>
            <hr>
            <pre style=\"background-color: #f8f8f8; padding: 10px; border-radius: 5px; white-space: pre-wrap;\">{body}</pre>
            """

        msg.attach(MIMEText(html_content, "html"))

        # Attachments
        if attachments:
            for file_path in attachments:
                if not os.path.exists(file_path):
                    logger.warning(f"Attachment not found: {file_path}")
                    continue
                # Prevent path traversal by restricting to a safe directory
                allowed_dir = os.path.abspath(os.getenv("ATTACHMENTS_DIR", "."))
                abs_path = os.path.abspath(file_path)
                if not abs_path.startswith(allowed_dir):
                    logger.warning(f"Attachment path traversal attempt blocked: {file_path}")
                    continue
                with open(abs_path, "rb") as f:
                    file_content = f.read()
                filename = os.path.basename(abs_path)
                if abs_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                    attachment = MIMEImage(file_content)
                else:
                    attachment = MIMEApplication(file_content)
                attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(attachment)

        # Support multiple recipients separated by commas
        recipients = [r.strip() for r in receiver.split(",") if r.strip()]

        # Send email using configured SMTP settings
        if smtp_security == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(sender, recipients, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if smtp_security == "starttls":
                    server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(sender, recipients, msg.as_string())

        logger.info(f"Email report sent successfully to {recipients}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email report: {str(e)}")
        return False