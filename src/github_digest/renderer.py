"""HTML and Markdown renderers for GitHub Trending reports."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from jinja2 import Environment, PackageLoader, select_autoescape

from github_digest.models import DailyReport, FailureReport, TrendingRepo


ENV = Environment(
    loader=PackageLoader("github_digest", "templates"),
    autoescape=select_autoescape(["html", "xml", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

_REPOSITORY_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+\Z")
_ACTIONS_PATH = re.compile(
    r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/actions/runs/([0-9]+)$"
)
_MARKDOWN_SPECIAL_CHARACTERS = "\\`*_{}[]<>()#+-.!|"


def render_digest(report: DailyReport) -> tuple[str, str]:
    """Render exactly five Trending repositories as an HTML email and Markdown."""
    if len(report.repositories) != 5:
        raise ValueError("A digest requires exactly 5 repositories")

    projects = [_project_context(repository) for repository in report.repositories]
    html = ENV.get_template("digest.html.j2").render(report=report, projects=projects)
    markdown = _render_markdown(report, projects)
    return html, markdown


def render_failure(report: FailureReport) -> str:
    """Render a safe, actionable HTML email for a failed digest execution."""
    return ENV.get_template("failure.html.j2").render(
        report=report,
        actions_url=_canonical_actions_url(report.actions_url),
    )


def _project_context(repository: TrendingRepo) -> dict[str, object]:
    _validate_repository_numbers(repository)
    return {
        "rank": repository.rank,
        "full_name": _normalize_text(repository.full_name, "full_name"),
        "language": _normalize_text(repository.language, "language"),
        "stars": repository.stars,
        "summary": _normalize_text(repository.summary_zh, "summary_zh"),
        "streak_label": _streak_label(repository.streak_days),
        "url": _canonical_repository_url(repository.url),
    }


def _streak_label(streak_days: int) -> str:
    if streak_days <= 1:
        return "今日首次上榜"
    return f"连续霸榜第 {streak_days} 天"


def _validate_repository_numbers(repository: TrendingRepo) -> None:
    _validate_positive_integer(repository.rank, "repository.rank")
    _validate_non_negative_integer(repository.stars, "repository.stars")
    _validate_positive_integer(repository.streak_days, "repository.streak_days")


def _validate_positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _validate_non_negative_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _normalize_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"repository.{field} must be a string")
    return re.sub(r"[\r\n]+", " ", value)


def _canonical_repository_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
        or len(path_parts) != 2
        or not all(_REPOSITORY_SEGMENT.fullmatch(part) for part in path_parts)
    ):
        return None
    return f"https://github.com/{path_parts[0]}/{path_parts[1]}"


def _canonical_actions_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    match = _ACTIONS_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        return None
    owner, repository, run_id = match.groups()
    return f"https://github.com/{owner}/{repository}/actions/runs/{run_id}"


def _escape_markdown(value: str) -> str:
    return re.sub(
        f"([{re.escape(_MARKDOWN_SPECIAL_CHARACTERS)}])",
        r"\\\1",
        value,
    )


def _render_markdown(report: DailyReport, projects: list[dict[str, object]]) -> str:
    lines = ["# GitHub Trending 全球 Top 5", "", f"日期：{report.report_date}", ""]
    for project in projects:
        url = project["url"]
        streak_label = project["streak_label"]
        rank = project["rank"]
        full_name = project["full_name"]
        language = project["language"]
        stars = project["stars"]
        summary = project["summary"]
        assert url is None or isinstance(url, str)
        assert isinstance(streak_label, str)
        assert isinstance(rank, int)
        assert isinstance(full_name, str)
        assert isinstance(language, str)
        assert isinstance(stars, int)
        assert isinstance(summary, str)
        escaped_name = _escape_markdown(full_name)
        lines.extend(
            [
                f"## {rank}. [{escaped_name}]({url})" if url else f"## {rank}. {escaped_name}",
                f"{streak_label} · {_escape_markdown(language)} · {stars:,} Stars",
                "",
                _escape_markdown(summary),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
