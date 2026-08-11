from __future__ import annotations

import pytest

from github_digest.config import ConfigError, load_config, parse_recipients


def test_parse_recipients_returns_one_valid_address() -> None:
    assert parse_recipients("wangyaoyi@bigo.sg") == ["wangyaoyi@bigo.sg"]


def test_parse_recipients_trims_and_deduplicates_case_insensitively() -> None:
    assert parse_recipients(
        "  First@Example.com, second@example.com, first@example.COM , third@example.com  "
    ) == ["First@Example.com", "second@example.com", "third@example.com"]


def test_parse_recipients_drops_invalid_entries_when_valid_entries_remain() -> None:
    assert parse_recipients("invalid, valid@example.com, missing-at.example.com") == [
        "valid@example.com"
    ]


def test_parse_recipients_raises_config_error_when_no_valid_entries() -> None:
    with pytest.raises(ConfigError, match="MAIL_TO"):
        parse_recipients("invalid, missing-at.example.com")


def test_load_config_reads_credentials_and_applies_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = {
        "GMAIL_USERNAME": "digest@example.com",
        "GMAIL_APP_PASSWORD": "app-password",
        "MAIL_TO": "first@example.com, SECOND@example.com",
        "GEMINI_API_KEY": "gemini-key",
        "DEEPSEEK_API_KEY": "deepseek-key",
        "GITHUB_TOKEN": "github-token",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    config = load_config()

    assert config.gmail_username == "digest@example.com"
    assert config.gmail_app_password == "app-password"
    assert config.recipients == ("first@example.com", "SECOND@example.com")
    assert config.gemini_api_key == "gemini-key"
    assert config.deepseek_api_key == "deepseek-key"
    assert config.github_token == "github-token"
    assert config.timezone == "Asia/Shanghai"
    assert config.top_count == 5
    assert config.history_dir == "reports/history"
