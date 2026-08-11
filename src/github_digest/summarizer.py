"""Chinese repository summaries with ordered AI provider fallback."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeAlias

import requests

from github_digest.models import TrendingRepo


@dataclass(frozen=True, slots=True)
class SummaryResult:
    text: str
    source: str


ProviderCallable: TypeAlias = Callable[[TrendingRepo], SummaryResult]
Provider: TypeAlias = tuple[str, ProviderCallable]


def build_prompt(repository: TrendingRepo) -> str:
    """Build the shared instruction and repository context for a provider."""
    description = repository.description[:12_000]
    context = (repository.readme or repository.description)[:12_000]
    return (
        "请用简体中文写一段不超过 200 个汉字的项目摘要。内容需自然地涵盖项目背景、"
        "解决的痛点，以及它为什么值得关注；不要使用标题、列表或营销语言。\n\n"
        f"项目：{repository.full_name}\n"
        f"描述：{description}\n"
        f"README 或项目描述：{context}"
    )


def summarize_with_fallback(repository: TrendingRepo, providers: Sequence[Provider]) -> SummaryResult:
    """Return the first concise provider result, or a repository-derived fallback."""
    for _, provider in providers:
        try:
            candidate = provider(repository)
        except Exception:
            continue
        if isinstance(candidate, SummaryResult) and isinstance(candidate.text, str):
            text = candidate.text.strip()
            if text and len(text) <= 200:
                return SummaryResult(text=text, source=candidate.source)

    fallback = repository.description.strip()[:200]
    if not fallback:
        fallback = f"{repository.full_name} 是今日 GitHub Trending 热门项目。"
    return SummaryResult(text=fallback, source="repository description")


def gemini_provider(api_key: str, model: str = "gemini-2.5-flash") -> ProviderCallable:
    """Create a Gemini provider callable."""
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def summarize(repository: TrendingRepo) -> SummaryResult:
        response = requests.post(
            endpoint,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": build_prompt(repository)}]}]},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return SummaryResult(
            text=payload["candidates"][0]["content"]["parts"][0]["text"],
            source="Gemini",
        )

    return summarize


def openai_compatible_provider(
    source: str, endpoint: str, api_key: str, model: str
) -> ProviderCallable:
    """Create a provider for OpenAI-compatible chat-completions APIs."""

    def summarize(repository: TrendingRepo) -> SummaryResult:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": build_prompt(repository)}],
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return SummaryResult(text=payload["choices"][0]["message"]["content"], source=source)

    return summarize
