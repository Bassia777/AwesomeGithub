"""GitHub REST API enrichment for trending repositories."""

from __future__ import annotations

import base64
import binascii
from typing import Any

import requests
import re

from github_digest.models import TrendingRepo


API_ROOT = "https://api.github.com"
_USER_AGENT = "github-trending-daily/0.1"


def enrich_repository(repository: TrendingRepo, token: str) -> TrendingRepo:
    """Populate a trending repository with GitHub metadata and its README."""
    repository_url = f"{API_ROOT}/repos/{repository.full_name}"
    response = requests.get(repository_url, headers=_headers(token), timeout=20)
    response.raise_for_status()

    metadata = _json_object(response)
    if metadata is not None:
        stars = _parse_stars(metadata.get("stargazers_count"))
        if stars is not None:
            repository.stars = stars
        repository.language = _value_or_default(metadata.get("language"), repository.language, "Unknown")
        repository.description = _value_or_default(
            metadata.get("description"), repository.description, ""
        )

    repository.readme = ""
    try:
        readme_response = requests.get(
            f"{repository_url}/readme", headers=_headers(token), timeout=20
        )
    except requests.RequestException:
        return repository
    if readme_response.ok:
        repository.readme = _decode_readme(_json_object(readme_response))
        repository.image_url = _first_readme_image(repository.readme, repository.url)
    return repository


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }


def _json_object(response: requests.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_stars(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def _value_or_default(value: object, existing: str, default: str) -> str:
    return value if isinstance(value, str) and value else existing or default


def _decode_readme(payload: dict[str, Any] | None) -> str:
    if payload is None or payload.get("encoding") != "base64":
        return ""
    content = payload.get("content")
    if not isinstance(content, str):
        return ""
    try:
        encoded_content = "".join(content.split())
        return base64.b64decode(encoded_content, validate=True).decode("utf-8", errors="replace")
    except (ValueError, binascii.Error):
        return ""


def _first_readme_image(readme: str, repository_url: str) -> str:
    if not isinstance(readme, str):
        return ""
    candidates: list[str] = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", readme):
        candidates.append(match.group(1).strip().split()[0])
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', readme, re.IGNORECASE):
        candidates.append(match.group(1).strip())
    resolved = [_resolve_readme_image(candidate, repository_url) for candidate in candidates]
    usable = [candidate for candidate in resolved if candidate]
    preferred = [candidate for candidate in usable if not _is_badge_image(candidate)]
    for candidate in preferred:
        if "/assets/" in candidate or "/images/" in candidate or "/img/" in candidate:
            return candidate
    return preferred[0] if preferred else ""


def _resolve_readme_image(candidate: str, repository_url: str) -> str:
    if candidate.startswith("https://"):
        return candidate
    identity = repository_url.removeprefix("https://github.com/").strip("/")
    if candidate.startswith("/"):
        return f"https://raw.githubusercontent.com/{identity}/HEAD{candidate}"
    return f"https://raw.githubusercontent.com/{identity}/HEAD/{candidate.lstrip('./')}"


def _is_badge_image(url: str) -> bool:
    lowered = url.casefold()
    return any(
        marker in lowered
        for marker in (
            "img.shields.io",
            "badge.fury.io",
            "github.com/actions/workflows",
            "github.com/marketplace",
            "badge",
            "socialify.git.ci",
            "opencollective.com",
        )
    )
