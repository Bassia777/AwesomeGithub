"""SMTP delivery for rendered GitHub Trending digest emails."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from github_digest.config import EMAIL_PATTERN


class MailerError(ValueError):
    """Raised when email delivery inputs are unsafe or invalid."""


_PLAIN_FALLBACK = "请使用支持 HTML 的邮件客户端查看本日报。"


def _is_safe_header(value: str) -> bool:
    return "\r" not in value and "\n" not in value


def _validate_inputs(
    username: str,
    app_password: str,
    recipients: tuple[str, ...],
    subject: str,
    html: str,
) -> None:
    if not isinstance(username, str) or not _is_safe_header(username) or not EMAIL_PATTERN.fullmatch(username):
        raise MailerError("Invalid sender email address")
    if not isinstance(recipients, tuple) or not recipients:
        raise MailerError("At least one recipient email address is required")
    if any(
        not isinstance(recipient, str)
        or not _is_safe_header(recipient)
        or not EMAIL_PATTERN.fullmatch(recipient)
        for recipient in recipients
    ):
        raise MailerError("Invalid recipient email address")
    if not isinstance(subject, str) or not _is_safe_header(subject):
        raise MailerError("Invalid email subject")
    if not isinstance(app_password, str) or not isinstance(html, str):
        raise MailerError("Invalid email delivery input")


def send_html_email(
    username: str,
    app_password: str,
    recipients: tuple[str, ...],
    subject: str,
    html: str,
) -> None:
    """Send an HTML digest via Gmail's SSL SMTP endpoint."""
    _validate_inputs(username, app_password, recipients, subject, html)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = ", ".join(recipients)
    message.set_content(_PLAIN_FALLBACK, charset="utf-8")
    message.add_alternative(html, subtype="html", charset="utf-8")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp_client:
        smtp_client.login(username, app_password)
        smtp_client.send_message(message)
