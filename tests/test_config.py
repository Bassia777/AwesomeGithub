from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import get_type_hints

import pytest

from github_digest.config import ConfigError, load_config, parse_recipients
from github_digest.models import DailyReport, FailureReport, TrendingRepo


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


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GMAIL_USERNAME", None),
        ("GMAIL_APP_PASSWORD", "   "),
        ("MAIL_TO", None),
        ("GEMINI_API_KEY", "   "),
        ("DEEPSEEK_API_KEY", None),
        ("GITHUB_TOKEN", "   "),
    ],
)
def test_load_config_rejects_each_missing_or_blank_required_value(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str | None
) -> None:
    required_values = {
        "GMAIL_USERNAME": "digest@example.com",
        "GMAIL_APP_PASSWORD": "app-password",
        "MAIL_TO": "recipient@example.com",
        "GEMINI_API_KEY": "gemini-key",
        "DEEPSEEK_API_KEY": "deepseek-key",
        "GITHUB_TOKEN": "github-token",
    }
    for environment_name, environment_value in required_values.items():
        monkeypatch.setenv(environment_name, environment_value)
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=name):
        load_config()


def test_config_is_frozen_and_excludes_secrets_from_its_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = {
        "GMAIL_USERNAME": "digest@example.com",
        "GMAIL_APP_PASSWORD": "super-secret-gmail-password",
        "MAIL_TO": "recipient@example.com",
        "GEMINI_API_KEY": "super-secret-gemini-key",
        "DEEPSEEK_API_KEY": "super-secret-deepseek-key",
        "GITHUB_TOKEN": "super-secret-github-token",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    config = load_config()

    with pytest.raises(FrozenInstanceError):
        config.timezone = "UTC"  # type: ignore[misc]
    for secret in (
        secrets["GMAIL_APP_PASSWORD"],
        secrets["GEMINI_API_KEY"],
        secrets["DEEPSEEK_API_KEY"],
        secrets["GITHUB_TOKEN"],
    ):
        assert secret not in repr(config)


def test_report_contracts_use_string_timestamps_and_serialize_repositories() -> None:
    repository = TrendingRepo(rank=1, full_name="owner/repo", url="https://example.com")
    report = DailyReport(
        report_date="2026-08-11",
        generated_at="2026-08-11T09:00:00+08:00",
        repositories=[repository],
    )
    failure = FailureReport(
        generated_at="2026-08-11T09:00:00+08:00",
        stage="email",
        attempts=3,
        error="SMTP authentication failed",
        likely_causes=("invalid app password",),
        actions_url="https://example.com/actions/1",
    )

    assert get_type_hints(DailyReport)["report_date"] is str
    assert get_type_hints(DailyReport)["generated_at"] is str
    assert get_type_hints(FailureReport)["generated_at"] is str
    assert repository.to_dict() == {
        "rank": 1,
        "full_name": "owner/repo",
        "url": "https://example.com",
        "description": "",
        "language": "Unknown",
        "stars": 0,
        "readme": "",
        "streak_days": 1,
        "summary_zh": "",
        "summary_source": "",
    }
    assert report.to_dict() == {
        "report_date": "2026-08-11",
        "generated_at": "2026-08-11T09:00:00+08:00",
        "scope": "global/all-languages/daily",
        "repositories": [repository.to_dict()],
    }
    assert failure == FailureReport(
        generated_at="2026-08-11T09:00:00+08:00",
        stage="email",
        attempts=3,
        error="SMTP authentication failed",
        likely_causes=("invalid app password",),
        actions_url="https://example.com/actions/1",
    )
