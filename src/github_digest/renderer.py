"""HTML and Markdown renderers for GitHub Trending reports."""

from __future__ import annotations

from urllib.parse import urlparse

from jinja2 import Environment, PackageLoader, select_autoescape

from github_digest.models import DailyReport, FailureReport, TrendingRepo


ENV = Environment(
    loader=PackageLoader("github_digest", "templates"),
    autoescape=select_autoescape(["html", "xml", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


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
        actions_url=_safe_url(report.actions_url),
    )


def _project_context(repository: TrendingRepo) -> dict[str, object]:
    return {
        "repository": repository,
        "streak_label": _streak_label(repository.streak_days),
        "url": _safe_url(repository.url),
    }


def _streak_label(streak_days: int) -> str:
    if streak_days <= 1:
        return "今日首次上榜"
    return f"连续霸榜第 {streak_days} 天"


def _safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc.lower() in {"github.com", "www.github.com"}:
        return value
    return "#"


def _render_markdown(report: DailyReport, projects: list[dict[str, object]]) -> str:
    lines = ["# GitHub Trending 全球 Top 5", "", f"日期：{report.report_date}", ""]
    for project in projects:
        repository = project["repository"]
        assert isinstance(repository, TrendingRepo)
        url = project["url"]
        streak_label = project["streak_label"]
        assert isinstance(url, str)
        assert isinstance(streak_label, str)
        lines.extend(
            [
                f"## {repository.rank}. [{repository.full_name}]({url})",
                f"{streak_label} · {repository.language} · {repository.stars:,} Stars",
                "",
                repository.summary_zh,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
