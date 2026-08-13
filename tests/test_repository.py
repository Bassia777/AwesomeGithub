from __future__ import annotations

import base64

import pytest
import requests
import responses

from github_digest.models import TrendingRepo
from github_digest.repository import API_ROOT, enrich_repository
from github_digest.repository import _first_readme_image


def _repository(**overrides: object) -> TrendingRepo:
    values: dict[str, object] = {
        "rank": 1,
        "full_name": "openai/codex",
        "url": "https://github.com/openai/codex",
    }
    values.update(overrides)
    return TrendingRepo(**values)  # type: ignore[arg-type]


@responses.activate
def test_enrich_repository_applies_metadata_and_decoded_readme() -> None:
    readme = "# Codex\n\nBuild with agents."
    encoded_readme = base64.b64encode(readme.encode()).decode()
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": 123456, "language": "Rust", "description": "Coding agent"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex/readme",
        json={"content": f"{encoded_readme[:12]}\n{encoded_readme[12:]}", "encoding": "base64"},
        status=200,
    )
    repository = _repository()

    result = enrich_repository(repository, "secret-token")

    assert result is repository
    assert repository.stars == 123456
    assert repository.language == "Rust"
    assert repository.description == "Coding agent"
    assert repository.readme == readme


@responses.activate
def test_enrich_repository_extracts_readme_html_images() -> None:
    readme = '<p><img src="https://raw.githubusercontent.com/openai/codex/main/banner.png"></p>'
    encoded_readme = base64.b64encode(readme.encode()).decode()
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex", json={}, status=200)
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex/readme",
        json={"content": encoded_readme, "encoding": "base64"},
        status=200,
    )
    repository = _repository()

    enrich_repository(repository, "secret-token")

    assert repository.image_url == "https://raw.githubusercontent.com/openai/codex/main/banner.png"


def test_first_readme_image_skips_badges_and_prefers_project_asset() -> None:
    readme = (
        "![Stars](https://img.shields.io/github/stars/acme/demo)\n"
        "<img src=\"https://raw.githubusercontent.com/acme/demo/main/assets/product.png\">"
    )
    assert _first_readme_image(readme, "https://github.com/acme/demo") == (
        "https://raw.githubusercontent.com/acme/demo/main/assets/product.png"
    )


def test_first_readme_image_resolves_relative_asset_to_raw_github() -> None:
    readme = "![产品截图](docs/images/product.png)"
    assert _first_readme_image(readme, "https://github.com/acme/demo") == (
        "https://raw.githubusercontent.com/acme/demo/HEAD/docs/images/product.png"
    )


def test_first_readme_image_never_returns_badge_when_only_badges_exist() -> None:
    readme = "![Stars](https://img.shields.io/github/stars/acme/demo)"
    assert _first_readme_image(readme, "https://github.com/acme/demo") == ""


@responses.activate
def test_enrich_repository_keeps_metadata_when_readme_is_not_found() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": 8, "language": "Python", "description": "A repository"},
        status=200,
    )
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    repository = _repository(readme="stale")

    enrich_repository(repository, "secret-token")

    assert repository.stars == 8
    assert repository.language == "Python"
    assert repository.description == "A repository"
    assert repository.readme == ""


@responses.activate
def test_enrich_repository_preserves_existing_metadata_for_null_fields() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": None, "language": None, "description": None},
        status=200,
    )
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    existing = _repository(stars=42, language="Go", description="Existing")

    enrich_repository(existing, "secret-token")

    assert existing.stars == 42
    assert existing.language == "Go"
    assert existing.description == "Existing"


@responses.activate
def test_enrich_repository_uses_defaults_for_empty_metadata_fields() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": None, "language": None, "description": None},
        status=200,
    )
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    empty = _repository(language="", description="")

    enrich_repository(empty, "secret-token")

    assert empty.stars == 0
    assert empty.language == "Unknown"
    assert empty.description == ""


@pytest.mark.parametrize(
    "stargazers_count",
    [None, "not-a-number", -1, True, 1.5],
    ids=["null", "malformed", "negative", "boolean", "fractional"],
)
@responses.activate
def test_enrich_repository_preserves_stars_for_invalid_metadata_values(
    stargazers_count: object,
) -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": stargazers_count},
        status=200,
    )
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    repository = _repository(stars=42)

    enrich_repository(repository, "secret-token")

    assert repository.stars == 42


@responses.activate
def test_enrich_repository_accepts_decimal_integer_string_stars() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": "123456"},
        status=200,
    )
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    repository = _repository()

    enrich_repository(repository, "secret-token")

    assert repository.stars == 123456


@responses.activate
def test_enrich_repository_preserves_metadata_for_non_object_json() -> None:
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex", json=[], status=200)
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    repository = _repository(stars=42, language="Go", description="Existing")

    enrich_repository(repository, "secret-token")

    assert repository.stars == 42
    assert repository.language == "Go"
    assert repository.description == "Existing"


@responses.activate
def test_enrich_repository_preserves_metadata_for_malformed_json() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        body="not valid JSON",
        content_type="application/json",
        status=200,
    )
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)
    repository = _repository(stars=42, language="Go", description="Existing")

    enrich_repository(repository, "secret-token")

    assert repository.stars == 42
    assert repository.language == "Go"
    assert repository.description == "Existing"


@responses.activate
def test_enrich_repository_propagates_metadata_http_errors() -> None:
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex", status=503)

    with pytest.raises(requests.HTTPError):
        enrich_repository(_repository(), "secret-token")

    assert len(responses.calls) == 1


@responses.activate
def test_enrich_repository_ignores_invalid_base64_readme() -> None:
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex", json={}, status=200)
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex/readme",
        json={"content": "not valid base64!", "encoding": "base64"},
        status=200,
    )
    repository = _repository(readme="stale")

    enrich_repository(repository, "secret-token")

    assert repository.readme == ""


@responses.activate
def test_enrich_repository_keeps_metadata_when_readme_request_fails() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex",
        json={"stargazers_count": 8, "language": "Python", "description": "A repository"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/openai/codex/readme",
        body=requests.ConnectionError("offline"),
    )
    repository = _repository(readme="stale")

    enrich_repository(repository, "secret-token")

    assert repository.stars == 8
    assert repository.language == "Python"
    assert repository.description == "A repository"
    assert repository.readme == ""


@responses.activate
def test_enrich_repository_sends_required_headers_and_timeout(monkeypatch) -> None:
    import github_digest.repository as repository_module

    requests: list[dict[str, object]] = []
    real_get = repository_module.requests.get

    def recording_get(*args: object, **kwargs: object):
        requests.append(dict(kwargs))
        return real_get(*args, **kwargs)

    monkeypatch.setattr(repository_module.requests, "get", recording_get)
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex", json={}, status=200)
    responses.add(responses.GET, f"{API_ROOT}/repos/openai/codex/readme", status=404)

    enrich_repository(_repository(), "secret-token")

    assert len(responses.calls) == 2
    for call in responses.calls:
        assert call.request.headers["Accept"] == "application/vnd.github+json"
        assert call.request.headers["Authorization"] == "Bearer secret-token"
        assert call.request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert call.request.headers["User-Agent"] == "github-trending-daily/0.1"
    assert [request["timeout"] for request in requests] == [20, 20]
