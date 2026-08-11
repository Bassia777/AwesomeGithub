from __future__ import annotations

from email.message import EmailMessage
import smtplib
from unittest.mock import MagicMock, patch

import pytest

from github_digest.mailer import MailerError, send_html_email


def test_send_html_email_delivers_utf8_multipart_message_to_all_recipients() -> None:
    recipients = ("first@example.com", "second@example.com")
    smtp_client = MagicMock()
    smtp_connection = MagicMock()
    smtp_connection.__enter__.return_value = smtp_client

    with patch("github_digest.mailer.smtplib.SMTP_SSL", return_value=smtp_connection) as smtp_ssl:
        send_html_email(
            "digest@example.com",
            "app-password",
            recipients,
            "GitHub Trending 日报",
            "<h1>今日趋势：你好</h1>",
        )

    smtp_ssl.assert_called_once_with("smtp.gmail.com", 465, timeout=30)
    smtp_client.login.assert_called_once_with("digest@example.com", "app-password")
    smtp_client.send_message.assert_called_once()
    message = smtp_client.send_message.call_args.args[0]
    assert isinstance(message, EmailMessage)
    assert message["Subject"] == "GitHub Trending 日报"
    assert message["From"] == "digest@example.com"
    assert message["To"] == "first@example.com, second@example.com"
    assert message.is_multipart()

    plain_part, html_part = message.iter_parts()
    assert plain_part.get_content_type() == "text/plain"
    assert plain_part.get_content_charset() == "utf-8"
    assert plain_part.get_content() == "请使用支持 HTML 的邮件客户端查看本日报。\n"
    assert html_part.get_content_type() == "text/html"
    assert html_part.get_content_charset() == "utf-8"
    assert html_part.get_content() == "<h1>今日趋势：你好</h1>\n"


@pytest.mark.parametrize(
    ("username", "recipients", "subject"),
    [
        ("digest@example.com", (), "Daily digest"),
        ("not-an-email", ("recipient@example.com",), "Daily digest"),
        ("digest@example.com", ("not-an-email",), "Daily digest"),
        ("digest@example.com", ("recipient@example.com",), "Hello\nBcc: victim@example.com"),
        ("digest\nBcc: victim@example.com", ("recipient@example.com",), "Daily digest"),
        ("digest@example.com", ("recipient\nBcc: victim@example.com",), "Daily digest"),
    ],
)
def test_send_html_email_rejects_unsafe_or_invalid_inputs_without_secret_disclosure(
    username: str, recipients: tuple[str, ...], subject: str
) -> None:
    password = "never-disclose-this-app-password"

    with pytest.raises(MailerError) as error:
        send_html_email(username, password, recipients, subject, "<p>Digest</p>")

    assert password not in str(error.value)
    assert password not in repr(error.value)


def test_send_html_email_propagates_smtp_authentication_errors() -> None:
    smtp_client = MagicMock()
    smtp_client.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
    smtp_connection = MagicMock()
    smtp_connection.__enter__.return_value = smtp_client

    with patch("github_digest.mailer.smtplib.SMTP_SSL", return_value=smtp_connection):
        with pytest.raises(smtplib.SMTPAuthenticationError, match="Authentication failed"):
            send_html_email(
                "digest@example.com",
                "app-password",
                ("recipient@example.com",),
                "Daily digest",
                "<p>Digest</p>",
            )
