"""GitHub daily trending page retrieval and parsing."""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from github_digest.models import TrendingRepo


TRENDING_URL = "https://github.com/trending?since=daily"
_GITHUB_URL = "https://github.com"
_USER_AGENT = "github-trending-daily/0.1"


class TrendingError(RuntimeError):
    """Raised when GitHub Trending cannot provide enough repositories."""


def parse_trending(html: str, top_count: int = 5) -> list[TrendingRepo]:
    """Parse exactly ``top_count`` valid repositories from Trending HTML."""
    soup = BeautifulSoup(html, "html.parser")
    repositories: list[TrendingRepo] = []

    for article in soup.select("article.Box-row"):
        link = article.select_one("h2 a[href]")
        if link is None:
            continue

        full_name = _normalise_full_name(link["href"])
        if full_name is None:
            continue

        description = _text_or_empty(article.select_one("p"))
        language = _text_or_empty(article.select_one("[itemprop='programmingLanguage']")) or "Unknown"
        stars_link = article.select_one("a[href$='/stargazers']")
        repositories.append(
            TrendingRepo(
                rank=len(repositories) + 1,
                full_name=full_name,
                url=f"{_GITHUB_URL}/{full_name}",
                description=description,
                language=language,
                stars=_parse_stars(_text_or_empty(stars_link)),
            )
        )
        if len(repositories) == top_count:
            break

    if len(repositories) != top_count:
        raise TrendingError(
            f"expected {top_count} valid trending repositories, found {len(repositories)}"
        )
    return repositories


def fetch_trending(top_count: int = 5, attempts: int = 3) -> list[TrendingRepo]:
    """Fetch and parse the daily Trending page, retrying transient failures."""
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                TRENDING_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=20,
            )
            response.raise_for_status()
            return parse_trending(response.text, top_count=top_count)
        except (requests.RequestException, TrendingError) as error:
            errors.append(f"attempt {attempt}: {error}")
            if attempt < attempts:
                time.sleep(attempt * 2)

    details = "; ".join(errors) or "no attempts were made"
    raise TrendingError(f"failed to fetch trending after {attempts} attempts: {details}")


def _normalise_full_name(href: str) -> str | None:
    path = urlsplit(href).path.strip("/")
    parts = path.split("/")
    if len(parts) != 2:
        return None

    owner, repository = ("".join(part.split()) for part in parts)
    if not owner or not repository:
        return None
    return f"{owner}/{repository}"


def _parse_stars(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else 0


def _text_or_empty(element: Tag | None) -> str:
    if element is None:
        return ""
    return element.get_text(" ", strip=True)
