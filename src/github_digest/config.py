from __future__ import annotations

import os
import re
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when required digest configuration is missing or invalid."""


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def parse_recipients(value: str) -> list[str]:
    """Return valid, unique recipients from a comma-separated MAIL_TO value."""
    recipients: list[str] = []
    seen: set[str] = set()
    for candidate in value.split(","):
        address = candidate.strip()
        normalized = address.casefold()
        if EMAIL_PATTERN.fullmatch(address) and normalized not in seen:
            recipients.append(address)
            seen.add(normalized)

    if not recipients:
        raise ConfigError("MAIL_TO must contain at least one valid email address")
    return recipients


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    gmail_username: str
    gmail_app_password: str
    recipients: tuple[str, ...]
    gemini_api_key: str
    deepseek_api_key: str
    github_token: str
    timezone: str = "Asia/Shanghai"
    top_count: int = 5
    history_dir: str = "reports/history"


def load_config() -> Config:
    """Load required credentials and recipients from environment variables."""
    return Config(
        gmail_username=_required("GMAIL_USERNAME"),
        gmail_app_password=_required("GMAIL_APP_PASSWORD"),
        recipients=tuple(parse_recipients(_required("MAIL_TO"))),
        gemini_api_key=_required("GEMINI_API_KEY"),
        deepseek_api_key=_required("DEEPSEEK_API_KEY"),
        github_token=_required("GITHUB_TOKEN"),
    )
