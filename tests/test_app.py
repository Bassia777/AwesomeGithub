from __future__ import annotations

from datetime import datetime
import logging
import smtplib
from zoneinfo import ZoneInfo

import pytest

from github_digest import app
from github_digest.config import Config
from github_digest.models import TrendingRepo
from github_digest.summarizer import ProviderError, SummaryResult
from github_digest.trending import TrendingError


FIXED_NOW = datetime(2026, 8, 11, 8, 30, 45, tzinfo=ZoneInfo("Asia/Shanghai"))


class FixedDateTime:
    @classmethod
    def now(cls, timezone: ZoneInfo) -> datetime:
        assert timezone.key == "Asia/Shanghai"
        return FIXED_NOW


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        gmail_username="digest@example.com",
        gmail_app_password="gmail-password-secret",
        recipients=("reader@example.com",),
        gemini_api_key="gemini-key-secret",
        deepseek_api_key="deepseek-key-secret",
        github_token="github-token-secret",
        history_dir=str(tmp_path / "history"),
    )


def repositories() -> list[TrendingRepo]:
    return [
        TrendingRepo(
            rank=rank,
            full_name=f"owner/repository-{rank}",
            url=f"https://github.com/owner/repository-{rank}",
            description=f"parsed description {rank}",
            language="Python",
            stars=rank * 100,
        )
        for rank in range(1, 6)
    ]


def patch_success_boundaries(monkeypatch, *, events: list[object] | None = None) -> None:
    event_log = events if events is not None else []
    monkeypatch.setattr(app, "datetime", FixedDateTime)
    monkeypatch.setattr(
        app,
        "fetch_trending",
        lambda count: event_log.append(("fetch", count)) or repositories(),
    )

    def enrich(repository: TrendingRepo, token: str) -> TrendingRepo:
        event_log.append(("enrich", repository.full_name, token))
        repository.readme = "enriched readme"
        return repository

    def apply_streaks(items, report_date, history_dir) -> None:
        materialized = list(items)
        event_log.append(("streaks", report_date.isoformat(), history_dir))
        for repository in materialized:
            repository.streak_days = repository.rank + 1

    def summarize(repository: TrendingRepo, config: Config) -> tuple[str, str]:
        event_log.append(("summary", repository.full_name))
        return (
            f"项目 {repository.rank} 的中文摘要，解决实际开发问题。",
            f"provider-{repository.rank}",
        )

    monkeypatch.setattr(app, "enrich_repository", enrich)
    monkeypatch.setattr(app, "apply_streaks", apply_streaks)
    monkeypatch.setattr(app, "summarize_repository", summarize)


def test_run_orders_normal_delivery_before_history_save(monkeypatch, config: Config) -> None:
    events: list[object] = []
    captured_report = None
    patch_success_boundaries(monkeypatch, events=events)

    def render(report):
        nonlocal captured_report
        captured_report = report
        events.append("render")
        return "<html>digest</html>", "# digest"

    monkeypatch.setattr(app, "render_digest", render)
    monkeypatch.setattr(
        app,
        "send_html_email",
        lambda username, password, recipients, subject, html: events.append(
            ("send", username, password, recipients, subject, html)
        ),
    )
    monkeypatch.setattr(
        app,
        "save_report",
        lambda report, markdown, history_dir: events.append(
            ("save", report, markdown, history_dir)
        ),
    )

    result = app.run(config)

    assert result == 0
    assert captured_report is not None
    assert captured_report.report_date == "2026-08-11"
    assert captured_report.generated_at == "2026-08-11T08:30:45+08:00"
    assert len(captured_report.repositories) == 5
    assert [repo.streak_days for repo in captured_report.repositories] == [
        2,
        3,
        4,
        5,
        6,
    ]
    assert [repo.summary_source for repo in captured_report.repositories] == [
        "provider-1",
        "provider-2",
        "provider-3",
        "provider-4",
        "provider-5",
    ]
    assert all(repo.summary_zh for repo in captured_report.repositories)
    send_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, tuple) and event[0] == "send"
    )
    save_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, tuple) and event[0] == "save"
    )
    assert send_index < save_index
    send_event = events[send_index]
    assert "2026-08-11" in send_event[4]
    assert send_event[5] == "<html>digest</html>"


@pytest.mark.parametrize("failure_index", range(5))
def test_each_enrichment_failure_preserves_parsed_repository_and_continues(
    monkeypatch, config: Config, failure_index: int, caplog
) -> None:
    patch_success_boundaries(monkeypatch)
    source_repositories = repositories()
    summarized: list[str] = []
    captured_report = None
    monkeypatch.setattr(app, "fetch_trending", lambda count: source_repositories)

    def enrich(repository: TrendingRepo, token: str) -> TrendingRepo:
        repository.description = "partially mutated"
        if repository.rank - 1 == failure_index:
            raise RuntimeError(f"request failed at https://api.github.com/?token={token}")
        return repository

    def summarize(repository: TrendingRepo, config: Config) -> tuple[str, str]:
        summarized.append(repository.full_name)
        return "这是一个有效的中文项目摘要。", "test-provider"

    def render(report):
        nonlocal captured_report
        captured_report = report
        return "digest", "markdown"

    monkeypatch.setattr(app, "enrich_repository", enrich)
    monkeypatch.setattr(app, "summarize_repository", summarize)
    monkeypatch.setattr(app, "render_digest", render)
    monkeypatch.setattr(app, "send_html_email", lambda *args: None)
    monkeypatch.setattr(app, "save_report", lambda *args: None)

    with caplog.at_level(logging.WARNING):
        result = app.run(config)

    assert result == 0
    assert summarized == [repository.full_name for repository in source_repositories]
    failed_repository = captured_report.repositories[failure_index]
    assert failed_repository.description == f"parsed description {failure_index + 1}"
    assert failed_repository is source_repositories[failure_index]
    assert source_repositories[failure_index].description == f"parsed description {failure_index + 1}"
    assert source_repositories[failure_index].full_name in caplog.text
    assert "RuntimeError" in caplog.text
    assert config.github_token not in caplog.text
    assert "https://api.github.com" not in caplog.text


@pytest.mark.parametrize(
    ("successful_provider", "expected_calls", "expected_source"),
    [
        ("Gemini", ["Gemini"], "Gemini"),
        ("GitHub Models", ["Gemini", "GitHub Models"], "GitHub Models"),
        ("DeepSeek", ["Gemini", "GitHub Models", "DeepSeek"], "DeepSeek"),
        (None, ["Gemini", "GitHub Models", "DeepSeek"], "repository description"),
    ],
)
def test_summarize_repository_assembles_ordered_provider_fallback(
    monkeypatch,
    config: Config,
    successful_provider: str | None,
    expected_calls: list[str],
    expected_source: str,
) -> None:
    calls: list[str] = []
    factory_calls: list[tuple[object, ...]] = []

    def provider(name: str):
        def summarize(repository: TrendingRepo) -> SummaryResult:
            calls.append(name)
            if name != successful_provider:
                raise ProviderError(f"{name} unavailable")
            return SummaryResult("这是一个内容完整的中文项目摘要。", "ignored source")

        return summarize

    def gemini_factory(api_key: str):
        factory_calls.append(("gemini", api_key))
        return provider("Gemini")

    def compatible_factory(source: str, endpoint: str, api_key: str, model: str):
        factory_calls.append((source, endpoint, api_key, model))
        return provider(source)

    monkeypatch.setattr(app, "gemini_provider", gemini_factory)
    monkeypatch.setattr(app, "openai_compatible_provider", compatible_factory)
    repository = repositories()[0]

    text, source = app.summarize_repository(repository, config)

    assert calls == expected_calls
    assert source == expected_source
    assert text == (
        "parsed description 1"
        if successful_provider is None
        else "这是一个内容完整的中文项目摘要。"
    )
    assert factory_calls == [
        ("gemini", config.gemini_api_key),
        (
            "GitHub Models",
            "https://models.github.ai/inference/chat/completions",
            config.github_token,
            "openai/gpt-4.1-mini",
        ),
        (
            "DeepSeek",
            "https://api.deepseek.com/chat/completions",
            config.deepseek_api_key,
            "deepseek-chat",
        ),
    ]


def test_trending_failure_sends_alert_with_stage_attempts_and_actions_url(
    monkeypatch, config: Config
) -> None:
    monkeypatch.setattr(app, "datetime", FixedDateTime)
    monkeypatch.setattr(
        app,
        "fetch_trending",
        lambda count: (_ for _ in ()).throw(TrendingError("three attempts exhausted")),
    )
    captured_failure = None
    deliveries: list[tuple[object, ...]] = []

    def render_failure(report):
        nonlocal captured_failure
        captured_failure = report
        return "<html>failure</html>"

    monkeypatch.setattr(app, "render_failure", render_failure)
    monkeypatch.setattr(app, "send_html_email", lambda *args: deliveries.append(args))
    monkeypatch.setattr(
        app,
        "save_report",
        lambda *args: pytest.fail("history must not be saved"),
    )
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "OpenAI/example-repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")

    result = app.run(config)

    assert result == 1
    assert captured_failure.stage == "GitHub Trending 抓取"
    assert captured_failure.attempts == 3
    assert (
        captured_failure.actions_url
        == "https://github.com/OpenAI/example-repo/actions/runs/12345"
    )
    assert any("GitHub" in cause for cause in captured_failure.likely_causes)
    assert len(deliveries) == 1
    assert deliveries[0][3] == "GitHub 热榜日报运行异常"
    assert deliveries[0][4] == "<html>failure</html>"


@pytest.mark.parametrize(
    ("failure_boundary", "expected_stage"),
    [("summary", "AI 摘要生成"), ("render", "日报渲染")],
)
def test_summary_or_render_failure_sends_alert_without_saving(
    monkeypatch, config: Config, failure_boundary: str, expected_stage: str
) -> None:
    patch_success_boundaries(monkeypatch)
    captured_failure = None
    deliveries: list[tuple[object, ...]] = []

    if failure_boundary == "summary":
        monkeypatch.setattr(
            app,
            "summarize_repository",
            lambda repository, config: (_ for _ in ()).throw(
                RuntimeError("summary failed")
            ),
        )
    else:
        monkeypatch.setattr(
            app,
            "render_digest",
            lambda report: (_ for _ in ()).throw(ValueError("render failed")),
        )

    def render_failure(report):
        nonlocal captured_failure
        captured_failure = report
        return "failure html"

    monkeypatch.setattr(app, "render_failure", render_failure)
    monkeypatch.setattr(app, "send_html_email", lambda *args: deliveries.append(args))
    monkeypatch.setattr(
        app,
        "save_report",
        lambda *args: pytest.fail("history must not be saved"),
    )

    result = app.run(config)

    assert result == 1
    assert captured_failure.stage == expected_stage
    assert captured_failure.attempts == 1
    assert len(deliveries) == 1
    assert deliveries[0][3] == "GitHub 热榜日报运行异常"


def test_normal_smtp_failure_then_alert_smtp_failure_propagates(
    monkeypatch, config: Config
) -> None:
    patch_success_boundaries(monkeypatch)
    monkeypatch.setattr(app, "render_digest", lambda report: ("digest", "markdown"))
    monkeypatch.setattr(app, "render_failure", lambda report: "failure")
    first_error = smtplib.SMTPException("normal delivery failed")
    alert_error = smtplib.SMTPAuthenticationError(535, b"alert authentication failed")
    delivery_errors = iter((first_error, alert_error))

    def fail_delivery(*args) -> None:
        raise next(delivery_errors)

    monkeypatch.setattr(app, "send_html_email", fail_delivery)
    monkeypatch.setattr(
        app,
        "save_report",
        lambda *args: pytest.fail("history must not be saved"),
    )

    with pytest.raises(smtplib.SMTPAuthenticationError) as caught:
        app.run(config)

    assert caught.value is alert_error


def test_failure_error_sanitizer_removes_configured_credentials_and_tokens(
    monkeypatch, config: Config
) -> None:
    monkeypatch.setattr(app, "datetime", FixedDateTime)
    secrets = (
        config.gmail_username,
        config.gmail_app_password,
        config.gemini_api_key,
        config.deepseek_api_key,
        config.github_token,
    )
    message = " | ".join(secrets) + "\n" + ("x" * 700)
    monkeypatch.setattr(
        app,
        "fetch_trending",
        lambda count: (_ for _ in ()).throw(TrendingError(message)),
    )
    captured_failure = None

    def render_failure(report):
        nonlocal captured_failure
        captured_failure = report
        return "failure"

    monkeypatch.setattr(app, "render_failure", render_failure)
    monkeypatch.setattr(app, "send_html_email", lambda *args: None)

    assert app.run(config) == 1
    assert len(captured_failure.error) <= 500
    assert "\n" not in captured_failure.error
    for secret in secrets:
        assert secret not in captured_failure.error
    assert "[REDACTED]" in captured_failure.error


def test_invalid_actions_environment_renders_unavailable_link(
    monkeypatch, config: Config
) -> None:
    monkeypatch.setattr(app, "datetime", FixedDateTime)
    monkeypatch.setattr(
        app,
        "fetch_trending",
        lambda count: (_ for _ in ()).throw(TrendingError("unavailable")),
    )
    delivered_html: list[str] = []
    monkeypatch.setattr(
        app,
        "send_html_email",
        lambda username, password, recipients, subject, html: delivered_html.append(html),
    )
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://secret.invalid/credential")
    monkeypatch.setenv("GITHUB_REPOSITORY", "invalid owner/repository")
    monkeypatch.setenv("GITHUB_RUN_ID", "-9")

    assert app.run(config) == 1
    assert len(delivered_html) == 1
    assert "Actions 运行链接不可用" in delivered_html[0]
    assert "secret.invalid" not in delivered_html[0]


def test_main_loads_config_runs_and_exits(monkeypatch, config: Config) -> None:
    monkeypatch.setattr(app, "load_config", lambda: config)
    monkeypatch.setattr(app, "run", lambda loaded: 7 if loaded is config else -1)

    with pytest.raises(SystemExit) as caught:
        app.main()

    assert caught.value.code == 7
