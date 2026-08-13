"""HTML and Markdown renderers for GitHub Trending reports."""

from __future__ import annotations

from datetime import date
import re
from urllib.parse import ParseResult, urlparse

from jinja2 import Environment, PackageLoader, select_autoescape

from github_digest.models import DailyReport, FailureReport, TrendingRepo


ENV = Environment(
    loader=PackageLoader("github_digest", "templates"),
    autoescape=select_autoescape(["html", "xml", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

_REPORT_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_OWNER = re.compile(r"[A-Za-z0-9-]+\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9._-]+\Z")
_RUN_ID = re.compile(r"[1-9][0-9]*\Z")
_MARKDOWN_SPECIAL_CHARACTERS = r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~"""
FALLBACK_IMAGE_URLS = ("https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1200&q=85", "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1200&q=85", "https://images.unsplash.com/photo-1511467687858-23d96c32e4ae?w=1200&q=85", "https://images.unsplash.com/photo-1531297484001-80022131f5a1?w=1200&q=85", "https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=1200&q=85")


def render_digest(report: DailyReport) -> tuple[str, str]:
    """Render exactly five Trending repositories as an HTML email and Markdown."""
    if len(report.repositories) != 5:
        raise ValueError("A digest requires exactly 5 repositories")

    report_date = _validated_report_date(report.report_date)
    for repository in report.repositories:
        _validate_repository_numbers(repository)
    _validate_top_five_ranks(report.repositories)
    projects = [_project_context(repository) for repository in report.repositories]
    html = ENV.get_template("digest.html.j2").render(
        report=report,
        report_date=report_date,
        projects=projects,
    )
    markdown = _render_markdown(report_date, projects)
    return html, markdown


def render_failure(report: FailureReport) -> str:
    """Render a safe, actionable HTML email for a failed digest execution."""
    _validate_positive_integer(report.attempts, "failure.attempts")
    return ENV.get_template("failure.html.j2").render(
        report=report,
        actions_url=_canonical_actions_url(report.actions_url),
    )


def _project_context(repository: TrendingRepo) -> dict[str, object]:
    identity = _repository_identity(repository.full_name)
    return {
        "rank": repository.rank,
        "full_name": _normalize_text(repository.full_name, "full_name"),
        "language": _normalize_text(repository.language, "language"),
        "stars": repository.stars,
        "stars_today": repository.stars_today,
        "image_url": FALLBACK_IMAGE_URLS[(repository.rank - 1) % len(FALLBACK_IMAGE_URLS)],
        "summary": _normalize_text(repository.summary_zh, "summary_zh"),
        "simple_summary": _normalize_text(repository.simple_summary_zh, "simple_summary_zh"),
        "streak_label": _streak_label(repository.streak_days),
        "url": _canonical_repository_url(repository.url, identity),
    }


def _streak_label(streak_days: int) -> str:
    if streak_days <= 1:
        return "今日首次上榜"
    return f"连续霸榜第 {streak_days} 天"


def _validate_repository_numbers(repository: TrendingRepo) -> None:
    _validate_positive_integer(repository.rank, "repository.rank")
    _validate_non_negative_integer(repository.stars, "repository.stars")
    _validate_positive_integer(repository.streak_days, "repository.streak_days")


def _validate_top_five_ranks(repositories: list[TrendingRepo]) -> None:
    if [repository.rank for repository in repositories] != [1, 2, 3, 4, 5]:
        raise ValueError("repository ranks must be exactly [1, 2, 3, 4, 5] in order")


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


def _validated_report_date(value: object) -> str:
    if not isinstance(value, str) or _REPORT_DATE.fullmatch(value) is None:
        raise ValueError("report.report_date must be an ISO YYYY-MM-DD date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("report.report_date must be an ISO YYYY-MM-DD date") from None
    return value


def _repository_identity(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    if len(parts) != 2 or not _is_valid_owner(parts[0]) or not _is_valid_repository(parts[1]):
        return None
    return parts[0], parts[1]


def _is_valid_owner(value: str) -> bool:
    return (
        1 <= len(value) <= 39
        and _OWNER.fullmatch(value) is not None
        and not value.startswith("-")
        and not value.endswith("-")
    )


def _is_valid_repository(value: str) -> bool:
    return (
        1 <= len(value) <= 100
        and value not in {".", ".."}
        and _REPOSITORY.fullmatch(value) is not None
    )


def _parse_exact_github_url(value: object) -> ParseResult | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        return None
    return parsed


def _canonical_repository_url(
    value: object, expected_identity: tuple[str, str] | None
) -> str | None:
    parsed = _parse_exact_github_url(value)
    if parsed is None or expected_identity is None:
        return None
    path = parsed.path.split("/")
    if len(path) != 3 or path[0] or not _is_valid_owner(path[1]) or not _is_valid_repository(path[2]):
        return None
    url_identity = path[1], path[2]
    if tuple(part.casefold() for part in url_identity) != tuple(
        part.casefold() for part in expected_identity
    ):
        return None
    return f"https://github.com/{expected_identity[0]}/{expected_identity[1]}"


def _canonical_actions_url(value: object) -> str | None:
    parsed = _parse_exact_github_url(value)
    if parsed is None:
        return None
    path = parsed.path.split("/")
    if (
        len(path) != 6
        or path[0]
        or not _is_valid_owner(path[1])
        or not _is_valid_repository(path[2])
        or path[3:5] != ["actions", "runs"]
        or _RUN_ID.fullmatch(path[5]) is None
    ):
        return None
    owner, repository, run_id = path[1], path[2], path[5]
    return f"https://github.com/{owner}/{repository}/actions/runs/{run_id}"


def _escape_markdown(value: str) -> str:
    return re.sub(
        f"([{re.escape(_MARKDOWN_SPECIAL_CHARACTERS)}])",
        r"\\\1",
        value,
    )


def _render_markdown(report_date: str, projects: list[dict[str, object]]) -> str:
    lines = ["# GitHub Trending 全球 Top 5", "", f"日期：{report_date}", ""]
    for project in projects:
        url = project["url"]
        streak_label = project["streak_label"]
        rank = project["rank"]
        full_name = project["full_name"]
        language = project["language"]
        stars = project["stars"]
        stars_today = project["stars_today"]
        summary = project["summary"]
        simple_summary = project["simple_summary"]
        assert url is None or isinstance(url, str)
        assert isinstance(streak_label, str)
        assert isinstance(rank, int)
        assert isinstance(full_name, str)
        assert isinstance(language, str)
        assert isinstance(stars, int)
        assert isinstance(stars_today, int)
        assert isinstance(summary, str)
        assert isinstance(simple_summary, str)
        escaped_name = _escape_markdown(full_name)
        lines.extend(
            [
                f"## {rank}. [{escaped_name}]({url})" if url else f"## {rank}. {escaped_name}",
                f"{streak_label} · {_escape_markdown(language)} · {stars:,} Stars · 今日新增 {stars_today:,} Stars",
                "",
                _escape_markdown(summary),
                "",
                f"一句话总结：{_escape_markdown(simple_summary)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
