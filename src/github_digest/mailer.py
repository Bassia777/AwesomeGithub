"""SMTP delivery for rendered GitHub Trending digest emails."""

from __future__ import annotations

import smtplib
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage

from github_digest.config import EMAIL_PATTERN


class MailerError(ValueError):
    """Raised when email delivery inputs are unsafe or invalid."""


_PLAIN_FALLBACK = "请使用支持 HTML 的邮件客户端查看本日报。"
_AMBIGUOUS_ADDRESS_CHARACTERS = frozenset(",;<>\"'")


def _is_safe_header(value: str) -> bool:
    return not any(character in "\r\n" or ord(character) < 32 or ord(character) == 127 for character in value)


def _canonical_address(value: str, error_message: str) -> str:
    if (
        not isinstance(value, str)
        or not _is_safe_header(value)
        or any(character.isspace() for character in value)
        or any(character in _AMBIGUOUS_ADDRESS_CHARACTERS for character in value)
    ):
        raise MailerError(error_message)
    try:
        address = Address(addr_spec=value).addr_spec
    except (HeaderParseError, TypeError, ValueError):
        raise MailerError(error_message) from None
    if address != value or not EMAIL_PATTERN.fullmatch(address):
        raise MailerError(error_message)
    return address


def _validate_inputs(
    username: str,
    app_password: str,
    recipients: tuple[str, ...],
    subject: str,
    html: str,
) -> None:
    _canonical_address(username, "Invalid sender email address")
    if not isinstance(recipients, tuple) or not recipients:
        raise MailerError("At least one recipient email address is required")
    if not isinstance(subject, str) or not _is_safe_header(subject):
        raise MailerError("Invalid email subject")
    if not isinstance(app_password, str) or not isinstance(html, str):
        raise MailerError("Invalid email delivery input")


def _canonical_recipients(recipients: tuple[str, ...]) -> tuple[str, ...]:
    canonical_recipients: list[str] = []
    seen: set[str] = set()
    for recipient in recipients:
        address = _canonical_address(recipient, "Invalid recipient email address")
        if address.casefold() not in seen:
            canonical_recipients.append(address)
            seen.add(address.casefold())
    return tuple(canonical_recipients)


def _build_message(username: str, recipient: str, subject: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = recipient
    message.set_content(_PLAIN_FALLBACK, charset="utf-8")
    message.add_alternative(html, subtype="html", charset="utf-8")
    return message


def send_html_email(
    username: str,
    app_password: str,
    recipients: tuple[str, ...],
    subject: str,
    html: str,
) -> None:
    """Send an HTML digest via Gmail's SSL SMTP endpoint."""
    _validate_inputs(username, app_password, recipients, subject, html)
    sender = _canonical_address(username, "Invalid sender email address")
    unique_recipients = _canonical_recipients(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp_client:
        smtp_client.login(sender, app_password)
        for recipient in unique_recipients:
            smtp_client.send_message(
                _build_message(sender, recipient, subject, html),
                from_addr=sender,
                to_addrs=[recipient],
            )
