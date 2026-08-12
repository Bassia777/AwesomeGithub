"""Application orchestration for the daily GitHub Trending digest."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from github_digest.config import Config, load_config
from github_digest.history import apply_streaks, save_report
from github_digest.mailer import send_html_email
from github_digest.models import DailyReport, FailureReport, TrendingRepo
from github_digest.renderer import render_digest, render_failure
from github_digest.repository import enrich_repository
from github_digest.summarizer import (
    gemini_provider,
    openai_compatible_provider,
    summarize_with_fallback,
)
from github_digest.trending import TrendingError, fetch_trending


LOGGER = logging.getLogger(__name__)

_NORMAL_SUBJECT_PREFIX = "GitHub 热榜日报"
_FAILURE_SUBJECT = "GitHub 热榜日报运行异常"
_GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
_DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
_REPOSITORY_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9._-]+\Z")
_RUN_ID = re.compile(r"[1-9][0-9]*\Z")


class AlertDeliveryError(RuntimeError):
    """A sanitized failure raised when the failure alert cannot be delivered."""

    def __init__(self, stage: str, category: str) -> None:
        self.stage = stage
        self.category = category
        super().__init__(f"Failure alert delivery failed at {stage} ({category})")


def summarize_repository(repository: TrendingRepo, config: Config) -> tuple[str, str]:
    """Summarize one repository through the configured provider fallback chain."""
    providers = (
        ("Gemini", gemini_provider(config.gemini_api_key)),
        (
            "GitHub Models",
            openai_compatible_provider(
                "GitHub Models",
                _GITHUB_MODELS_ENDPOINT,
                config.github_token,
                "openai/gpt-4.1-mini",
            ),
        ),
        (
            "DeepSeek",
            openai_compatible_provider(
                "DeepSeek",
                _DEEPSEEK_ENDPOINT,
                config.deepseek_api_key,
                "deepseek-chat",
            ),
        ),
    )
    result = summarize_with_fallback(repository, providers)
    return result.text, result.source


def run(config: Config) -> int:
    """Run the digest pipeline, alerting recipients when an ordinary stage fails."""
    now: datetime | None = None
    stage = "初始化时区"
    alert_delivery_error: AlertDeliveryError | None = None

    try:
        now = datetime.now(ZoneInfo(config.timezone))

        stage = "GitHub Trending 抓取"
        repositories = fetch_trending(config.top_count)

        stage = "GitHub 仓库信息补全"
        enriched_repositories: list[TrendingRepo] = []
        for repository in repositories:
            candidate = replace(repository)
            try:
                enriched_repositories.append(
                    enrich_repository(candidate, config.github_token)
                )
            except Exception as error:
                LOGGER.warning(
                    "Repository enrichment failed for %s (%s); using parsed data",
                    _sanitized_repository_name(repository.full_name),
                    type(error).__name__,
                )
                enriched_repositories.append(repository)
        repositories = enriched_repositories

        stage = "历史连续上榜计算"
        apply_streaks(repositories, now.date(), Path(config.history_dir))

        stage = "AI 摘要生成"
        for repository in repositories:
            repository.summary_zh, repository.summary_source = summarize_repository(
                repository, config
            )

        report = DailyReport(
            report_date=now.date().isoformat(),
            generated_at=now.isoformat(),
            repositories=repositories,
        )

        stage = "日报渲染"
        html, markdown = render_digest(report)

        stage = "日报邮件发送"
        send_html_email(
            config.qq_email_username,
            config.qq_email_auth_code,
            config.recipients,
            f"{_NORMAL_SUBJECT_PREFIX} - {report.report_date}",
            html,
        )

        stage = "历史报告保存"
        save_report(report, markdown, Path(config.history_dir))
        return 0
    except Exception as error:
        failure_time = now if now is not None else datetime.now(timezone.utc)
        attempts = (
            3
            if stage == "GitHub Trending 抓取" and isinstance(error, TrendingError)
            else 1
        )
        failure = FailureReport(
            generated_at=failure_time.isoformat(),
            stage=stage,
            attempts=attempts,
            error=_sanitize_error(error, config),
            likely_causes=_likely_causes(stage),
            actions_url=_actions_url(),
        )
        LOGGER.error(
            "Digest pipeline failed at %s (%s): %s",
            failure.stage,
            type(error).__name__,
            failure.error,
        )
        try:
            failure_html = render_failure(failure)
            send_html_email(
                config.qq_email_username,
                config.qq_email_auth_code,
                config.recipients,
                _FAILURE_SUBJECT,
                failure_html,
            )
        except Exception as alert_error:
            alert_delivery_error = AlertDeliveryError(
                failure.stage, type(alert_error).__name__
            )
            LOGGER.error(
                "Failure alert delivery failed at %s (%s)",
                failure.stage,
                type(alert_error).__name__,
            )
        else:
            return 1

    if alert_delivery_error is not None:
        raise alert_delivery_error from None
    raise RuntimeError("unreachable orchestration state")


def _sanitize_error(error: Exception, config: Config) -> str:
    """Return a concise error message with configured credentials removed."""
    try:
        message = str(error)
    except Exception:
        message = type(error).__name__

    sensitive_values = {
        config.qq_email_username,
        config.qq_email_auth_code,
        config.gemini_api_key,
        config.deepseek_api_key,
        config.github_token,
        *config.recipients,
    }
    for sensitive_value in sorted(
        (value for value in sensitive_values if value), key=len, reverse=True
    ):
        message = message.replace(sensitive_value, "[REDACTED]")

    message = re.sub(r"[\x00-\x1f\x7f]+", " ", message)
    message = re.sub(r"\s+", " ", message).strip()
    return (message or type(error).__name__)[:500]


def _sanitized_repository_name(full_name: object) -> str:
    if isinstance(full_name, str) and _REPOSITORY_NAME.fullmatch(full_name):
        return full_name[:141]
    return "<invalid repository>"


def _likely_causes(stage: str) -> tuple[str, ...]:
    if stage == "初始化时区":
        return ("配置的时区名称无效或运行环境缺少时区数据",)
    if stage == "GitHub Trending 抓取":
        return (
            "GitHub Trending 页面暂时不可用或结构发生变化",
            "GitHub 网络连接、限流或上游服务异常",
        )
    if stage == "GitHub 仓库信息补全":
        return ("GitHub API 网络、鉴权或限流异常",)
    if stage == "历史连续上榜计算":
        return ("历史报告目录不可读或历史数据格式异常",)
    if stage == "AI 摘要生成":
        return ("外部摘要服务不可用、鉴权失败或响应格式异常",)
    if stage == "日报渲染":
        return ("日报数据不完整或模板渲染异常",)
    if stage == "日报邮件发送":
        return ("SMTP 网络、QQ 邮箱鉴权或收件人配置异常",)
    if stage == "历史报告保存":
        return ("历史报告目录权限、磁盘空间或文件发布异常",)
    return ("运行环境或配置异常",)


def _actions_url() -> str:
    """Build a canonical public GitHub Actions run URL from trusted-shaped env data."""
    server_url = os.environ.get("GITHUB_SERVER_URL", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")

    try:
        parsed_server = urlsplit(server_url)
    except ValueError:
        return ""
    if (
        parsed_server.scheme != "https"
        or parsed_server.netloc.casefold() != "github.com"
        or parsed_server.username is not None
        or parsed_server.password is not None
        or parsed_server.port is not None
        or parsed_server.path not in {"", "/"}
        or parsed_server.query
        or parsed_server.fragment
    ):
        return ""

    parts = repository.split("/")
    if len(parts) != 2:
        return ""
    owner, repository_name = parts
    if (
        not 1 <= len(owner) <= 39
        or _OWNER.fullmatch(owner) is None
        or not 1 <= len(repository_name) <= 100
        or repository_name in {".", ".."}
        or _REPOSITORY.fullmatch(repository_name) is None
        or _RUN_ID.fullmatch(run_id) is None
    ):
        return ""
    return f"https://github.com/{owner}/{repository_name}/actions/runs/{run_id}"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(run(load_config()))


if __name__ == "__main__":
    main()
