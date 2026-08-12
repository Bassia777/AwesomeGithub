from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import logging
from pathlib import Path
import smtplib
import traceback
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
        qq_email_username="sender@qq.com",
        qq_email_auth_code="qq-auth-secret",
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


@pytest.mark.parametrize("alert_boundary", ["render", "send"])
def test_alert_failure_raises_safe_exception_without_secret_exception_chains(
    monkeypatch, config: Config, alert_boundary: str, caplog
) -> None:
    monkeypatch.setattr(app, "datetime", FixedDateTime)
    primary_raw_message = "primary raw failure: " + " | ".join(
        (
            config.qq_email_username,
            config.qq_email_auth_code,
            config.recipients[0],
            config.gemini_api_key,
            config.deepseek_api_key,
            config.github_token,
        )
    )
    private_alert_recipient = "private-alert-recipient@example.com"
    secondary_raw_message = "secondary raw failure includes private recipient"
    monkeypatch.setattr(
        app,
        "fetch_trending",
        lambda count: (_ for _ in ()).throw(TrendingError(primary_raw_message)),
    )

    if alert_boundary == "render":
        monkeypatch.setattr(
            app,
            "render_failure",
            lambda report: (_ for _ in ()).throw(
                RuntimeError(f"{secondary_raw_message}: {private_alert_recipient}")
            ),
        )
        monkeypatch.setattr(
            app,
            "send_html_email",
            lambda *args: pytest.fail("alert send must not run after render failure"),
        )
        expected_category = "RuntimeError"
    else:
        monkeypatch.setattr(app, "render_failure", lambda report: "failure")

        def refuse_alert(*args) -> None:
            raise smtplib.SMTPRecipientsRefused(
                {private_alert_recipient: (550, secondary_raw_message.encode())}
            )

        monkeypatch.setattr(app, "send_html_email", refuse_alert)
        expected_category = "SMTPRecipientsRefused"

    with caplog.at_level(logging.ERROR):
        with pytest.raises(app.AlertDeliveryError) as caught:
            app.run(config)

    formatted_traceback = "".join(
        traceback.format_exception(
            type(caught.value), caught.value, caught.value.__traceback__
        )
    )
    exposed_text = formatted_traceback + caplog.text + str(caught.value)
    for private_value in (
        primary_raw_message,
        secondary_raw_message,
        private_alert_recipient,
        config.qq_email_username,
        config.qq_email_auth_code,
        *config.recipients,
        config.gemini_api_key,
        config.deepseek_api_key,
        config.github_token,
    ):
        assert private_value not in exposed_text
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert caught.value.stage == "GitHub Trending 抓取"
    assert caught.value.category == expected_category
    assert "GitHub Trending 抓取" in caplog.text
    assert "TrendingError" in caplog.text
    assert "[REDACTED]" in caplog.text


def test_invalid_timezone_sends_alert_with_safe_utc_timestamp(
    monkeypatch, config: Config
) -> None:
    invalid_config = replace(config, timezone="Private/invalid-timezone")
    captured_failure = None
    deliveries: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        app,
        "fetch_trending",
        lambda count: pytest.fail("trending fetch must not run"),
    )

    def capture_failure(report):
        nonlocal captured_failure
        captured_failure = report
        return "failure html"

    monkeypatch.setattr(app, "render_failure", capture_failure)
    monkeypatch.setattr(app, "send_html_email", lambda *args: deliveries.append(args))

    result = app.run(invalid_config)

    assert result == 1
    assert captured_failure.stage == "初始化时区"
    assert captured_failure.attempts == 1
    generated_at = datetime.fromisoformat(captured_failure.generated_at)
    assert generated_at.utcoffset() == timedelta(0)
    assert len(deliveries) == 1
    assert deliveries[0][3] == "GitHub 热榜日报运行异常"


def test_streak_failure_alerts_before_any_summary_render_or_save(
    monkeypatch, config: Config, caplog
) -> None:
    events: list[object] = []
    patch_success_boundaries(monkeypatch, events=events)
    captured_failure = None

    def fail_streaks(items, report_date, history_dir) -> None:
        events.append("streak-failure")
        raise OSError("history read failed")

    def render_alert(report):
        nonlocal captured_failure
        captured_failure = report
        events.append("failure-render")
        return "failure"

    monkeypatch.setattr(app, "apply_streaks", fail_streaks)
    monkeypatch.setattr(app, "render_failure", render_alert)
    monkeypatch.setattr(
        app,
        "send_html_email",
        lambda username, password, recipients, subject, html: events.append(
            ("send", subject)
        ),
    )
    monkeypatch.setattr(
        app,
        "render_digest",
        lambda report: pytest.fail("normal rendering must not run"),
    )
    monkeypatch.setattr(
        app,
        "save_report",
        lambda *args: pytest.fail("history save must not run"),
    )

    with caplog.at_level(logging.ERROR):
        assert app.run(config) == 1
    assert captured_failure.stage == "历史连续上榜计算"
    assert captured_failure.attempts == 1
    assert events[-3:] == [
        "streak-failure",
        "failure-render",
        ("send", "GitHub 热榜日报运行异常"),
    ]
    assert not any(
        isinstance(event, tuple) and event[0] == "summary" for event in events
    )
    assert "history read failed" in caplog.text


def test_normal_send_failure_then_successful_alert_returns_one_without_save(
    monkeypatch, config: Config, caplog
) -> None:
    events: list[object] = []
    patch_success_boundaries(monkeypatch, events=events)
    captured_failure = None

    def render_digest(report):
        events.append("digest-render")
        return "digest", "markdown"

    def render_alert(report):
        nonlocal captured_failure
        captured_failure = report
        events.append("failure-render")
        return "failure"

    def deliver(username, password, recipients, subject, html) -> None:
        events.append(("send", subject))
        if subject != "GitHub 热榜日报运行异常":
            raise smtplib.SMTPException("normal send failed")

    monkeypatch.setattr(app, "render_digest", render_digest)
    monkeypatch.setattr(app, "render_failure", render_alert)
    monkeypatch.setattr(app, "send_html_email", deliver)
    monkeypatch.setattr(
        app,
        "save_report",
        lambda *args: pytest.fail("history save must not run"),
    )

    with caplog.at_level(logging.ERROR):
        assert app.run(config) == 1
    assert captured_failure.stage == "日报邮件发送"
    assert events[-4:] == [
        "digest-render",
        ("send", "GitHub 热榜日报 - 2026-08-11"),
        "failure-render",
        ("send", "GitHub 热榜日报运行异常"),
    ]
    assert "normal send failed" in caplog.text


def test_history_save_failure_alerts_after_normal_delivery_without_retrying_save(
    monkeypatch, config: Config, caplog
) -> None:
    events: list[object] = []
    patch_success_boundaries(monkeypatch, events=events)
    history_dir = config.history_dir
    marker_path = Path(history_dir) / "existing.marker"
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text("unchanged", encoding="utf-8")
    captured_failure = None

    def render_digest(report):
        events.append("digest-render")
        return "digest", "markdown"

    def deliver(username, password, recipients, subject, html) -> None:
        events.append(("send", subject))

    def fail_save(report, markdown, target_history_dir) -> None:
        events.append(("save", target_history_dir))
        raise OSError("publication failed")

    def render_alert(report):
        nonlocal captured_failure
        captured_failure = report
        events.append("failure-render")
        return "failure"

    monkeypatch.setattr(app, "render_digest", render_digest)
    monkeypatch.setattr(app, "send_html_email", deliver)
    monkeypatch.setattr(app, "save_report", fail_save)
    monkeypatch.setattr(app, "render_failure", render_alert)

    with caplog.at_level(logging.ERROR):
        assert app.run(config) == 1
    assert captured_failure.stage == "历史报告保存"
    assert marker_path.read_text(encoding="utf-8") == "unchanged"
    assert events[-5:] == [
        "digest-render",
        ("send", "GitHub 热榜日报 - 2026-08-11"),
        ("save", marker_path.parent),
        "failure-render",
        ("send", "GitHub 热榜日报运行异常"),
    ]
    assert sum(
        1 for event in events if isinstance(event, tuple) and event[0] == "save"
    ) == 1
    assert "publication failed" in caplog.text


def test_failure_error_sanitizer_removes_configured_credentials_and_tokens(
    monkeypatch, config: Config
) -> None:
    monkeypatch.setattr(app, "datetime", FixedDateTime)
    secrets = (
        config.qq_email_username,
        config.qq_email_auth_code,
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
