from __future__ import annotations

from pathlib import Path

import pytest
import responses

from github_digest.trending import TRENDING_URL, TrendingError, fetch_trending, parse_trending


FIXTURE = Path(__file__).with_name("fixtures") / "trending.html"


def _article(href: str | None) -> str:
    link = "<a>owner/repository</a>" if href is None else f'<a href="{href}">owner/repository</a>'
    return f'<article class="Box-row"><h2>{link}</h2></article>'


def test_parse_trending_skips_invalid_and_duplicate_articles() -> None:
    repositories = parse_trending(FIXTURE.read_text(), top_count=5)

    assert len(repositories) == 5
    assert [repository.rank for repository in repositories] == [1, 2, 3, 4, 5]
    assert [repository.full_name for repository in repositories] == [
        "owner/repo-1",
        "owner/repo-2",
        "owner/repo-3",
        "owner/repo-4",
        "owner/repo-5",
    ]
    assert all(repository.full_name.count("/") == 1 for repository in repositories)
    assert all(repository.url.startswith("https://github.com/") for repository in repositories)


def test_parse_trending_accepts_relative_and_absolute_github_repository_hrefs() -> None:
    html = _article(" /owner/repository ") + _article("https://github.com/other/project")

    repositories = parse_trending(html, top_count=2)

    assert [repository.full_name for repository in repositories] == ["owner/repository", "other/project"]


@pytest.mark.parametrize(
    "href",
    [
        "https://gitlab.com/owner/repository",
        "/owner/repository/extra",
        "/own er/repository",
        "/owner/repository!",
        "?repository=owner/repository",
        "https://github.com/owner/repository?tab=readme",
    ],
)
def test_parse_trending_rejects_invalid_repository_hrefs(href: str) -> None:
    with pytest.raises(TrendingError, match="expected 1"):
        parse_trending(_article(href), top_count=1)


def test_parse_trending_skips_an_h2_link_without_an_href() -> None:
    with pytest.raises(TrendingError, match="expected 1"):
        parse_trending(_article(None), top_count=1)


def test_parse_trending_reads_metadata_and_uses_fallbacks() -> None:
    repositories = parse_trending(FIXTURE.read_text(), top_count=5)

    assert repositories[0].description == "First repository description."
    assert repositories[0].language == "Python"
    assert repositories[0].stars == 1234
    assert repositories[3].description == ""
    assert repositories[3].language == "Unknown"


def test_parse_trending_rejects_fewer_than_requested_valid_repositories() -> None:
    html_parts = FIXTURE.read_text().split('<article class="Box-row">')
    only_four_repositories = '<article class="Box-row">'.join(html_parts[:5]) + "</body></html>"

    with pytest.raises(TrendingError, match="expected 5"):
        parse_trending(only_four_repositories, top_count=5)


@responses.activate
def test_fetch_trending_retries_three_times_after_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[int] = []
    for _ in range(3):
        responses.add(responses.GET, TRENDING_URL, status=503, body="Service Unavailable")
    monkeypatch.setattr("github_digest.trending.time.sleep", sleeps.append)

    with pytest.raises(TrendingError) as error:
        fetch_trending()

    assert "after 3 attempts" in str(error.value)
    assert "attempt 1" in str(error.value)
    assert "attempt 2" in str(error.value)
    assert "attempt 3" in str(error.value)
    assert "503" in str(error.value)
    assert len(responses.calls) == 3
    assert sleeps == [2, 4]
    assert all(call.request.url == TRENDING_URL for call in responses.calls)
    assert all(call.request.headers["User-Agent"] == "github-trending-daily/0.1" for call in responses.calls)


@responses.activate
def test_fetch_trending_retries_then_returns_parsed_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[int] = []
    responses.add(responses.GET, TRENDING_URL, status=503, body="Service Unavailable")
    responses.add(responses.GET, TRENDING_URL, status=200, body=FIXTURE.read_text())
    monkeypatch.setattr("github_digest.trending.time.sleep", sleeps.append)

    repositories = fetch_trending()

    assert TRENDING_URL == "https://github.com/trending?since=daily"
    assert len(repositories) == 5
    assert len(responses.calls) == 2
    assert sleeps == [2]
    assert all(call.request.url == TRENDING_URL for call in responses.calls)
    assert all(call.request.headers["User-Agent"] == "github-trending-daily/0.1" for call in responses.calls)


@responses.activate
def test_fetch_trending_retries_after_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    html_parts = FIXTURE.read_text().split('<article class="Box-row">')
    only_four_repositories = '<article class="Box-row">'.join(html_parts[:10]) + "</body></html>"
    sleeps: list[int] = []
    responses.add(responses.GET, TRENDING_URL, status=200, body=only_four_repositories)
    responses.add(responses.GET, TRENDING_URL, status=200, body=FIXTURE.read_text())
    monkeypatch.setattr("github_digest.trending.time.sleep", sleeps.append)

    repositories = fetch_trending()

    assert len(repositories) == 5
    assert len(responses.calls) == 2
    assert sleeps == [2]
