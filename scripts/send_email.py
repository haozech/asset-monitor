"""
QQ Email SMTP Sender
Sends notification emails via QQ SMTP.
Recipient receives WeChat notification via QQ Mail's WeChat reminder feature.

Configure via environment variables or GitHub Secrets:
  SMTP_USER     - QQ email address (e.g., 123456@qq.com)
  SMTP_PASSWORD - QQ SMTP authorization code (16 chars, NOT QQ password)
  SMTP_TO       - Recipient (defaults to SMTP_USER if not set)
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime


def send_notification(subject, body):
    """Send email notification. Reads SMTP config from environment variables."""

    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_to = os.environ.get("SMTP_TO", smtp_user)

    if not smtp_user or not smtp_password:
        print("\n[!] SMTP not configured. Skipping email send.")
        print("Set SMTP_USER and SMTP_PASSWORD env vars to enable email notifications.")
        print(f"Would have sent:\n  To: {smtp_to or '(not set)'}\n  Subject: {subject}\n")
        return False

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = smtp_to
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15)
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [smtp_to], msg.as_string())
        server.quit()
        print(f"[OK] Email sent to {smtp_to} - {subject[:40]}")
        return True
    except Exception as e:
        print(f"[FAIL] Email send failed: {e}")
        return False


# ── Self-test ──
if __name__ == "__main__":
    print("Email sender self-test")
    print(f"SMTP_USER: {'✓ set' if os.environ.get('SMTP_USER') else '✗ not set'}")
    print(f"SMTP_PASSWORD: {'✓ set' if os.environ.get('SMTP_PASSWORD') else '✗ not set'}")
    print(f"SMTP_TO: {os.environ.get('SMTP_TO', '(defaults to SMTP_USER)')}")

    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"):
        send_notification(
            "Asset Monitor · Self-Test",
            f"邮件推送功能测试通过\n\n时间: {datetime.now().isoformat()}\n\n如果您收到此邮件，说明 SMTP 配置正确。"
        )
    else:
        print("\nTo test email sending, set environment variables and run:")
        print("  $env:SMTP_USER='chenhaoze94@qq.com'")
        print("  $env:SMTP_PASSWORD='your_smtp_auth_code'")
        print("  python send_email.py")
