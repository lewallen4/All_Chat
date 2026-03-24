"""
All_Chat - Email Service
Async SMTP email sending for verification and notifications.
"""

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging

from core.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html_body: str, text_body: str = ""):
    """Send email via configured SMTP. Fails silently with logging."""
    message = MIMEMultipart("alternative")
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject

    if text_body:
        message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=False,
            start_tls=settings.SMTP_TLS,
        )
        logger.info(f"Email sent to {to}: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        raise


def _base_template(content: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body {{ font-family: 'Segoe UI', sans-serif; background: #0d0d1a; color: #e0d9ff; margin: 0; padding: 20px; }}
        .card {{ background: #1a1a2e; border: 1px solid #3d2a7a; border-radius: 12px; max-width: 520px;
                 margin: 40px auto; padding: 40px; }}
        .logo {{ font-size: 28px; font-weight: 900; color: #b07aff; letter-spacing: -1px; margin-bottom: 24px; }}
        .btn {{ display: inline-block; background: #7c3aed; color: #fff; padding: 14px 32px;
                border-radius: 8px; text-decoration: none; font-weight: 600; margin: 24px 0; }}
        .footer {{ font-size: 12px; color: #6b5a8a; margin-top: 32px; }}
        p {{ line-height: 1.7; color: #c4b5e0; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="logo">all_chat</div>
        {content}
        <div class="footer">If you didn't request this, you can safely ignore this email.</div>
      </div>
    </body>
    </html>
    """


async def send_verification_email(to: str, username: str, token: str):
    verify_url = f"https://{settings.ALLOWED_ORIGINS[0].replace('https://', '')}/verify-email?token={token}"
    html = _base_template(f"""
        <p>Hey <strong>{username}</strong>, welcome to All_Chat!</p>
        <p>Please verify your email address to activate your account.</p>
        <a href="{verify_url}" class="btn">Verify Email Address</a>
        <p>This link expires in {settings.EMAIL_VERIFY_EXPIRE_HOURS} hours.</p>
    """)
    await send_email(to, "Verify your All_Chat account", html,
                     f"Verify your email: {verify_url}")


async def send_password_reset_email(to: str, username: str, token: str):
    reset_url = f"https://{settings.ALLOWED_ORIGINS[0].replace('https://', '')}/reset-password?token={token}"
    html = _base_template(f"""
        <p>Hey <strong>{username}</strong>,</p>
        <p>We received a request to reset your All_Chat password.</p>
        <a href="{reset_url}" class="btn">Reset Password</a>
        <p>This link expires in {settings.PASSWORD_RESET_EXPIRE_HOURS} hours.</p>
    """)
    await send_email(to, "Reset your All_Chat password", html,
                     f"Reset your password: {reset_url}")


async def send_new_message_notification(to: str, from_username: str):
    html = _base_template(f"""
        <p>You have a new encrypted message from <strong>{from_username}</strong> on All_Chat.</p>
        <p>Log in to read it — messages are end-to-end encrypted and can only be read in the app.</p>
        <a href="https://{settings.ALLOWED_ORIGINS[0].replace('https://', '')}/messages" class="btn">
            Open Messages
        </a>
    """)
    await send_email(to, f"New message from {from_username}", html)
