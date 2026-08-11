from __future__ import annotations

from pathlib import Path

import pytest
import requests

from github_digest.trending import TRENDING_URL, TrendingError, fetch_trending, parse_trending


FIXTURE = Path(__file__).with_name("fixtures") / "trending.html"


class FakeResponse:
    def __init__(self, text: str, status_error: requests.RequestException | None = None) -> None:
        self.text = text
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise self.status_error


def test_parse_trending_returns_the_first_five_normalized_repositories() -> None:
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


def test_fetch_trending_retries_three_times_after_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    sleeps: list[int] = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse("", requests.HTTPError("503 Service Unavailable"))

    monkeypatch.setattr("github_digest.trending.requests.get", fake_get)
    monkeypatch.setattr("github_digest.trending.time.sleep", sleeps.append)

    with pytest.raises(TrendingError, match="after 3 attempts"):
        fetch_trending()

    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_fetch_trending_uses_daily_url_and_returns_parsed_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse(FIXTURE.read_text())

    monkeypatch.setattr("github_digest.trending.requests.get", fake_get)

    repositories = fetch_trending()

    assert TRENDING_URL == "https://github.com/trending?since=daily"
    assert len(repositories) == 5
    assert calls == [
        (
            "https://github.com/trending?since=daily",
            {"headers": {"User-Agent": "github-trending-daily/0.1"}, "timeout": 20},
        )
    ]
