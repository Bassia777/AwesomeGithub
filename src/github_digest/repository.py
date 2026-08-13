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
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", readme):
        candidate = match.group(1).strip().split()[0]
        if candidate.startswith("https://"):
            return candidate
        if candidate.startswith("/"):
            return f"https://github.com{candidate}"
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', readme, re.IGNORECASE):
        candidate = match.group(1).strip()
        if candidate.startswith("https://"):
            return candidate
        if candidate.startswith("/"):
            return f"https://github.com{candidate}"
    return ""
