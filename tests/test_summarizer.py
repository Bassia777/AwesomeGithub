from __future__ import annotations

import json

import pytest
import requests
import responses

from github_digest.models import TrendingRepo
from github_digest.summarizer import (
    SummaryResult,
    build_prompt,
    gemini_provider,
    openai_compatible_provider,
    summarize_with_fallback,
)


def _repository(**overrides: object) -> TrendingRepo:
    values: dict[str, object] = {
        "rank": 1,
        "full_name": "openai/codex",
        "url": "https://github.com/openai/codex",
        "description": "An agentic coding tool.",
    }
    values.update(overrides)
    return TrendingRepo(**values)  # type: ignore[arg-type]


def test_summarize_uses_only_the_first_valid_provider() -> None:
    called: list[str] = []

    def first(_: TrendingRepo) -> SummaryResult:
        called.append("first")
        return SummaryResult(text="  首个可用摘要。  ", source="First result")

    def later(_: TrendingRepo) -> SummaryResult:
        called.append("later")
        return SummaryResult(text="不应调用", source="Later result")

    result = summarize_with_fallback(_repository(), (("First", first), ("Later", later)))

    assert result == SummaryResult(text="首个可用摘要。", source="First result")
    assert called == ["first"]


def test_summarize_skips_errors_and_invalid_results_until_success() -> None:
    def raises(_: TrendingRepo) -> SummaryResult:
        raise requests.ConnectionError("offline")

    def overlong(_: TrendingRepo) -> SummaryResult:
        return SummaryResult(text="长" * 201, source="long")

    def empty(_: TrendingRepo) -> SummaryResult:
        return SummaryResult(text=" \n ", source="empty")

    def valid(_: TrendingRepo) -> SummaryResult:
        return SummaryResult(text="有效摘要", source="valid result")

    result = summarize_with_fallback(
        _repository(), (("broken", raises), ("long", overlong), ("empty", empty), ("valid", valid))
    )

    assert result == SummaryResult(text="有效摘要", source="valid result")


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("描述" * 201, "描述" * 100),
        ("   ", "openai/codex 是今日 GitHub Trending 热门项目。"),
    ],
)
def test_summarize_falls_back_to_repository_description(
    description: str, expected: str
) -> None:
    result = summarize_with_fallback(
        _repository(description=description),
        (("broken", lambda _: SummaryResult(text="", source="broken")),),
    )

    assert result == SummaryResult(text=expected, source="repository description")


@pytest.mark.parametrize(
    ("text", "expected_source"),
    [("  " + "好" * 200 + "  ", "provider"), ("好" * 201, "repository description")],
)
def test_summarize_strips_whitespace_and_enforces_200_character_limit(
    text: str, expected_source: str
) -> None:
    result = summarize_with_fallback(
        _repository(),
        (("provider", lambda _: SummaryResult(text=text, source="provider result")),),
    )

    assert result.source == ("provider result" if expected_source == "provider" else expected_source)
    assert result.text == ("好" * 200 if expected_source == "provider" else "An agentic coding tool.")


def test_build_prompt_requests_required_concise_chinese_summary_and_truncates_readme() -> None:
    readme = "a" * 12_000 + "SHOULD-NOT-APPEAR"
    prompt = build_prompt(_repository(readme=readme))

    assert "简体中文" in prompt
    assert "200" in prompt
    assert "项目背景" in prompt
    assert "解决的痛点" in prompt
    assert "值得关注" in prompt
    assert "标题" in prompt and "列表" in prompt and "营销" in prompt
    assert "openai/codex" in prompt
    assert "An agentic coding tool." in prompt
    assert "a" * 12_000 in prompt
    assert "SHOULD-NOT-APPEAR" not in prompt


def test_build_prompt_truncates_description_when_it_is_the_only_source_material() -> None:
    description = "d" * 12_000 + "DESCRIPTION-TAIL"

    prompt = build_prompt(_repository(description=description, readme=""))

    assert "d" * 12_000 in prompt
    assert "DESCRIPTION-TAIL" not in prompt


@responses.activate
def test_gemini_provider_posts_expected_request_and_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    responses.add(
        responses.POST,
        endpoint,
        match=[responses.matchers.query_param_matcher({"key": "gemini-key"})],
        json={"candidates": [{"content": {"parts": [{"text": "Gemini 摘要"}]}}]},
        status=200,
    )
    observed: dict[str, object] = {}
    real_post = requests.post

    def recording_post(*args: object, **kwargs: object) -> requests.Response:
        observed["timeout"] = kwargs["timeout"]
        return real_post(*args, **kwargs)

    monkeypatch.setattr("github_digest.summarizer.requests.post", recording_post)

    name, provider = gemini_provider("gemini-key", model="gemini-test")
    result = provider(_repository())

    assert name == "Gemini"
    assert result == SummaryResult(text="Gemini 摘要", source="Gemini")
    assert observed["timeout"] == 45
    request = responses.calls[0].request
    assert request.url == endpoint + "?key=gemini-key"
    assert json.loads(request.body or "{}") == {
        "contents": [{"parts": [{"text": build_prompt(_repository())}]}]
    }


@responses.activate
@pytest.mark.parametrize(
    ("source", "endpoint"),
    [
        ("GitHub Models", "https://models.inference.ai.azure.com/chat/completions"),
        ("DeepSeek", "https://api.deepseek.com/chat/completions"),
    ],
)
def test_openai_compatible_provider_posts_authorized_request_and_parses_response(
    source: str, endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses.add(
        responses.POST,
        endpoint,
        json={"choices": [{"message": {"content": "兼容摘要"}}]},
        status=200,
    )

    observed: dict[str, object] = {}
    real_post = requests.post

    def recording_post(*args: object, **kwargs: object) -> requests.Response:
        observed["timeout"] = kwargs["timeout"]
        return real_post(*args, **kwargs)

    monkeypatch.setattr("github_digest.summarizer.requests.post", recording_post)

    name, provider = openai_compatible_provider(source, endpoint, "api-key", "chosen-model")
    result = provider(_repository())

    assert name == source
    assert result == SummaryResult(text="兼容摘要", source=source)
    assert observed["timeout"] == 45
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer api-key"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.body or "{}") == {
        "model": "chosen-model",
        "messages": [{"role": "user", "content": build_prompt(_repository())}],
    }


@pytest.mark.parametrize(
    "failure",
    [
        lambda _: (_ for _ in ()).throw(requests.ConnectionError("offline")),
        lambda _: (_ for _ in ()).throw(requests.HTTPError("503")),
        lambda _: (_ for _ in ()).throw(KeyError("choices")),
        lambda _: None,
    ],
    ids=["network", "status", "malformed-payload", "non-string-payload"],
)
def test_summarize_falls_through_provider_failures(failure: object) -> None:
    result = summarize_with_fallback(
        _repository(),
        (("bad", failure), ("good", lambda _: SummaryResult("后备提供方成功", "good"))),  # type: ignore[arg-type]
    )

    assert result == SummaryResult(text="后备提供方成功", source="good")


@responses.activate
def test_gemini_http_status_failure_falls_through_to_next_provider() -> None:
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    responses.add(responses.POST, endpoint, status=500)
    _, gemini = gemini_provider("gemini-key")

    result = summarize_with_fallback(
        _repository(),
        (("Gemini", gemini), ("next", lambda _: SummaryResult("后备成功", "Next"))),
    )

    assert result == SummaryResult("后备成功", "Next")


@responses.activate
@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ("not JSON", "application/json"),
        (json.dumps({"candidates": []}), "application/json"),
    ],
    ids=["malformed-json", "malformed-payload"],
)
def test_gemini_malformed_response_falls_through_to_next_provider(
    body: str, content_type: str
) -> None:
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    responses.add(responses.POST, endpoint, body=body, content_type=content_type, status=200)
    _, gemini = gemini_provider("gemini-key")

    result = summarize_with_fallback(
        _repository(),
        (("Gemini", gemini), ("next", lambda _: SummaryResult("后备成功", "Next"))),
    )

    assert result == SummaryResult("后备成功", "Next")


@responses.activate
@pytest.mark.parametrize(
    ("endpoint", "response_kwargs"),
    [
        ("https://api.deepseek.com/chat/completions", {"body": requests.ConnectionError("offline")}),
        ("https://models.inference.ai.azure.com/chat/completions", {"status": 503}),
    ],
    ids=["connection-error", "status-error"],
)
def test_openai_compatible_failure_falls_through_to_next_provider(
    endpoint: str, response_kwargs: dict[str, object]
) -> None:
    responses.add(responses.POST, endpoint, **response_kwargs)
    _, provider = openai_compatible_provider("Compatible", endpoint, "api-key", "model")

    result = summarize_with_fallback(
        _repository(),
        (("Compatible", provider), ("next", lambda _: SummaryResult("后备成功", "Next"))),
    )

    assert result == SummaryResult("后备成功", "Next")
