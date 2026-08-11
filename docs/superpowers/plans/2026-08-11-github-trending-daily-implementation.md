# GitHub Trending Daily Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GitHub Actions automation that emails a configurable list of recipients a five-card Chinese GitHub Daily Trending digest every morning, with streak tracking, multi-provider AI fallback, persistent history, and failure-analysis emails.

**Architecture:** A small Python package orchestrates focused modules for configuration, Trending parsing, repository enrichment, streak history, AI summarization, HTML rendering, and SMTP delivery. GitHub Actions runs the package on a schedule or manually, then commits successful JSON and Markdown reports back to the repository.

**Tech Stack:** Python 3.12, requests, BeautifulSoup4, Jinja2, pytest, responses, GitHub Actions, Gmail SMTP, Gemini API, GitHub Models, DeepSeek API.

---

## File map

- `pyproject.toml`: package metadata, runtime dependencies, pytest configuration, and console entry point.
- `src/github_digest/__init__.py`: package marker.
- `src/github_digest/models.py`: shared dataclasses and serialization contracts.
- `src/github_digest/config.py`: environment configuration and recipient parsing.
- `src/github_digest/trending.py`: GitHub Trending request, retry, and HTML parsing.
- `src/github_digest/repository.py`: GitHub REST API enrichment and README retrieval.
- `src/github_digest/history.py`: previous-day lookup, streak calculation, and report persistence.
- `src/github_digest/summarizer.py`: Gemini → GitHub Models → DeepSeek → repository-description fallback.
- `src/github_digest/renderer.py`: normal and failure HTML/Markdown rendering.
- `src/github_digest/mailer.py`: Gmail SMTP delivery.
- `src/github_digest/app.py`: orchestration and exit behavior.
- `src/github_digest/templates/digest.html.j2`: light five-card email template.
- `src/github_digest/templates/failure.html.j2`: failure-analysis email template.
- `tests/fixtures/trending.html`: stable Trending HTML fixture with at least six repositories.
- `tests/test_config.py`: configuration and recipient validation tests.
- `tests/test_trending.py`: parser, filtering, retry, and failure tests.
- `tests/test_repository.py`: GitHub enrichment fallback tests.
- `tests/test_history.py`: streak and persistence tests.
- `tests/test_summarizer.py`: provider order, validation, and fallback tests.
- `tests/test_renderer.py`: UTF-8, five-card, and failure-email snapshot assertions.
- `tests/test_mailer.py`: SMTP envelope and recipient tests.
- `tests/test_app.py`: end-to-end orchestration tests with mocked boundaries.
- `.github/workflows/daily-digest.yml`: scheduled/manual workflow and successful-history commit.
- `README.md`: setup, Secrets, manual test, schedule, and troubleshooting instructions.

### Task 1: Project scaffold, shared models, and configurable recipients

**Files:**
- Create: `pyproject.toml`
- Create: `src/github_digest/__init__.py`
- Create: `src/github_digest/models.py`
- Create: `src/github_digest/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing recipient and configuration tests**

```python
# tests/test_config.py
import pytest

from github_digest.config import ConfigError, load_config, parse_recipients


def test_parse_single_recipient():
    assert parse_recipients("wangyaoyi@bigo.sg") == ["wangyaoyi@bigo.sg"]


def test_parse_multiple_recipients_trims_and_deduplicates():
    raw = " wangyaoyi@bigo.sg, user@qq.com,wangyaoyi@bigo.sg "
    assert parse_recipients(raw) == ["wangyaoyi@bigo.sg", "user@qq.com"]


def test_parse_recipients_drops_invalid_when_valid_remain():
    assert parse_recipients("bad-address,user@gmail.com") == ["user@gmail.com"]


def test_parse_recipients_rejects_empty_valid_set():
    with pytest.raises(ConfigError, match="MAIL_TO"):
        parse_recipients("bad-address")


def test_load_config_requires_mail_and_provider_credentials(monkeypatch):
    values = {
        "GMAIL_USERNAME": "sender@gmail.com",
        "GMAIL_APP_PASSWORD": "app-password",
        "MAIL_TO": "one@qq.com,two@bigo.sg",
        "GEMINI_API_KEY": "gemini-key",
        "DEEPSEEK_API_KEY": "deepseek-key",
        "GITHUB_TOKEN": "github-token",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    config = load_config()

    assert config.recipients == ("one@qq.com", "two@bigo.sg")
    assert config.timezone == "Asia/Shanghai"
    assert config.top_count == 5
```

- [ ] **Step 2: Run the tests and verify the package does not exist yet**

Run: `python -m pytest tests/test_config.py -v`

Expected: FAIL during import with `ModuleNotFoundError: No module named 'github_digest'`.

- [ ] **Step 3: Add package metadata and dependencies**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "github-trending-daily"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4>=4.12,<5",
  "jinja2>=3.1,<4",
  "requests>=2.32,<3",
]

[project.optional-dependencies]
test = [
  "pytest>=8.3,<9",
  "responses>=0.25,<1",
]

[project.scripts]
github-trending-digest = "github_digest.app:main"

[tool.setuptools.package-data]
github_digest = ["templates/*.j2"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/github_digest/__init__.py
"""GitHub Trending daily digest package."""
```

- [ ] **Step 4: Implement shared models and configuration**

```python
# src/github_digest/models.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TrendingRepo:
    rank: int
    full_name: str
    url: str
    description: str = ""
    language: str = "Unknown"
    stars: int = 0
    readme: str = ""
    streak_days: int = 1
    summary_zh: str = ""
    summary_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DailyReport:
    report_date: str
    generated_at: str
    scope: str = "global/all-languages/daily"
    repositories: list[TrendingRepo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "generated_at": self.generated_at,
            "scope": self.scope,
            "repositories": [repo.to_dict() for repo in self.repositories],
        }


@dataclass(slots=True)
class FailureReport:
    generated_at: str
    stage: str
    attempts: int
    error: str
    likely_causes: tuple[str, ...]
    actions_url: str
```

```python
# src/github_digest/config.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass


class ConfigError(ValueError):
    pass


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def parse_recipients(raw: str) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for candidate in raw.split(","):
        email = candidate.strip()
        normalized = email.casefold()
        if not EMAIL_RE.fullmatch(email) or normalized in seen:
            continue
        seen.add(normalized)
        recipients.append(email)
    if not recipients:
        raise ConfigError("MAIL_TO must contain at least one valid email address")
    return recipients


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    gmail_username: str
    gmail_app_password: str
    recipients: tuple[str, ...]
    gemini_api_key: str
    deepseek_api_key: str
    github_token: str
    timezone: str = "Asia/Shanghai"
    top_count: int = 5
    history_dir: str = "reports/history"


def load_config() -> Config:
    return Config(
        gmail_username=_required("GMAIL_USERNAME"),
        gmail_app_password=_required("GMAIL_APP_PASSWORD"),
        recipients=tuple(parse_recipients(_required("MAIL_TO"))),
        gemini_api_key=_required("GEMINI_API_KEY"),
        deepseek_api_key=_required("DEEPSEEK_API_KEY"),
        github_token=_required("GITHUB_TOKEN"),
    )
```

- [ ] **Step 5: Run tests and commit the scaffold**

Run: `python -m pip install -e '.[test]' && python -m pytest tests/test_config.py -v`

Expected: 5 tests PASS.

```bash
git add pyproject.toml src/github_digest tests/test_config.py
git commit -m "feat: add digest configuration and models"
```

### Task 2: Trending parser with retry and valid-five enforcement

**Files:**
- Create: `src/github_digest/trending.py`
- Create: `tests/fixtures/trending.html`
- Create: `tests/test_trending.py`

- [ ] **Step 1: Save a deterministic Trending fixture**

Create `tests/fixtures/trending.html` with these six deterministic entries:

```html
<!DOCTYPE html><html lang="en"><body>
<article class="Box-row">
  <h2><a href="/owner/repo-1">owner / repo-1</a></h2>
  <p>Repository one description.</p>
  <span itemprop="programmingLanguage">Python</span>
  <a href="/owner/repo-1/stargazers">1,001</a>
  <span>500 stars today</span>
</article>
<article class="Box-row"><h2><a href="/owner/repo-2">owner / repo-2</a></h2><p>Repository two.</p><span itemprop="programmingLanguage">Rust</span><a href="/owner/repo-2/stargazers">902</a><span>400 stars today</span></article>
<article class="Box-row"><h2><a href="/owner/repo-3">owner / repo-3</a></h2><p>Repository three.</p><span itemprop="programmingLanguage">Go</span><a href="/owner/repo-3/stargazers">803</a><span>300 stars today</span></article>
<article class="Box-row"><h2><a href="/owner/repo-4">owner / repo-4</a></h2><p>Repository four.</p><span itemprop="programmingLanguage">TypeScript</span><a href="/owner/repo-4/stargazers">704</a><span>200 stars today</span></article>
<article class="Box-row"><h2><a href="/owner/repo-5">owner / repo-5</a></h2><p>Repository five.</p><span itemprop="programmingLanguage">Java</span><a href="/owner/repo-5/stargazers">605</a><span>100 stars today</span></article>
<article class="Box-row"><h2><a href="/owner/repo-6">owner / repo-6</a></h2><p>Repository six.</p><span itemprop="programmingLanguage">C++</span><a href="/owner/repo-6/stargazers">506</a><span>50 stars today</span></article>
</body></html>
```

- [ ] **Step 2: Write failing parser and retry tests**

```python
# tests/test_trending.py
from pathlib import Path

import pytest
import responses

from github_digest.trending import TrendingError, fetch_trending, parse_trending


FIXTURE = Path("tests/fixtures/trending.html").read_text(encoding="utf-8")


def test_parse_trending_returns_exactly_five_ranked_repositories():
    repos = parse_trending(FIXTURE, top_count=5)
    assert len(repos) == 5
    assert [repo.rank for repo in repos] == [1, 2, 3, 4, 5]
    assert all("/" in repo.full_name for repo in repos)
    assert all(repo.url.startswith("https://github.com/") for repo in repos)


def test_parse_trending_rejects_fewer_than_five_valid_repositories():
    with pytest.raises(TrendingError, match="expected 5"):
        parse_trending("<article class='Box-row'></article>", top_count=5)


@responses.activate
def test_fetch_trending_retries_three_times_then_fails(monkeypatch):
    monkeypatch.setattr("github_digest.trending.time.sleep", lambda _: None)
    for _ in range(3):
        responses.add(responses.GET, "https://github.com/trending?since=daily", status=503)
    with pytest.raises(TrendingError, match="after 3 attempts"):
        fetch_trending(top_count=5)
    assert len(responses.calls) == 3
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_trending.py -v`

Expected: FAIL because `github_digest.trending` does not exist.

- [ ] **Step 4: Implement request, selectors, normalization, and retry**

```python
# src/github_digest/trending.py
from __future__ import annotations

import time

import requests
from bs4 import BeautifulSoup

from github_digest.models import TrendingRepo


TRENDING_URL = "https://github.com/trending?since=daily"


class TrendingError(RuntimeError):
    pass


def parse_trending(html: str, top_count: int = 5) -> list[TrendingRepo]:
    soup = BeautifulSoup(html, "html.parser")
    repositories: list[TrendingRepo] = []
    for article in soup.select("article.Box-row"):
        link = article.select_one("h2 a[href]")
        if link is None:
            continue
        full_name = "/".join(part.strip() for part in link.get_text(" ", strip=True).split("/") if part.strip())
        if full_name.count("/") != 1:
            continue
        description_node = article.select_one("p")
        language_node = article.select_one("[itemprop='programmingLanguage']")
        repositories.append(
            TrendingRepo(
                rank=len(repositories) + 1,
                full_name=full_name,
                url=f"https://github.com/{full_name}",
                description=description_node.get_text(" ", strip=True) if description_node else "",
                language=language_node.get_text(" ", strip=True) if language_node else "Unknown",
            )
        )
        if len(repositories) == top_count:
            break
    if len(repositories) != top_count:
        raise TrendingError(f"expected {top_count} repositories, parsed {len(repositories)}")
    return repositories


def fetch_trending(top_count: int = 5, attempts: int = 3) -> list[TrendingRepo]:
    errors: list[str] = []
    headers = {"User-Agent": "github-trending-daily/0.1"}
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(TRENDING_URL, headers=headers, timeout=20)
            response.raise_for_status()
            return parse_trending(response.text, top_count=top_count)
        except (requests.RequestException, TrendingError) as exc:
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise TrendingError(f"Trending fetch failed after {attempts} attempts: {'; '.join(errors)}")
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_trending.py -v`

Expected: all Trending tests PASS.

```bash
git add src/github_digest/trending.py tests/fixtures/trending.html tests/test_trending.py
git commit -m "feat: parse GitHub daily trending"
```

### Task 3: GitHub repository enrichment with graceful README fallback

**Files:**
- Create: `src/github_digest/repository.py`
- Create: `tests/test_repository.py`

- [ ] **Step 1: Write failing GitHub API enrichment tests**

```python
# tests/test_repository.py
import responses

from github_digest.models import TrendingRepo
from github_digest.repository import enrich_repository


@responses.activate
def test_enrich_repository_adds_api_metadata_and_readme():
    responses.get(
        "https://api.github.com/repos/openai/codex",
        json={"stargazers_count": 12345, "language": "Rust", "description": "Coding agent"},
        status=200,
    )
    responses.get(
        "https://api.github.com/repos/openai/codex/readme",
        json={"content": "IyBDb2RleA==", "encoding": "base64"},
        status=200,
    )
    repo = TrendingRepo(rank=1, full_name="openai/codex", url="https://github.com/openai/codex")
    result = enrich_repository(repo, token="token")
    assert result.stars == 12345
    assert result.language == "Rust"
    assert result.description == "Coding agent"
    assert result.readme == "# Codex"


@responses.activate
def test_enrich_repository_keeps_metadata_when_readme_fails():
    responses.get(
        "https://api.github.com/repos/openai/codex",
        json={"stargazers_count": 10, "language": None, "description": "Fallback description"},
        status=200,
    )
    responses.get("https://api.github.com/repos/openai/codex/readme", status=404)
    repo = TrendingRepo(rank=1, full_name="openai/codex", url="https://github.com/openai/codex")
    result = enrich_repository(repo, token="token")
    assert result.description == "Fallback description"
    assert result.language == "Unknown"
    assert result.readme == ""
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `python -m pytest tests/test_repository.py -v`

Expected: FAIL because `github_digest.repository` does not exist.

- [ ] **Step 3: Implement GitHub metadata and README retrieval**

```python
# src/github_digest/repository.py
from __future__ import annotations

import base64

import requests

from github_digest.models import TrendingRepo


API_ROOT = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-trending-daily/0.1",
    }


def enrich_repository(repo: TrendingRepo, token: str) -> TrendingRepo:
    metadata = requests.get(f"{API_ROOT}/repos/{repo.full_name}", headers=_headers(token), timeout=20)
    metadata.raise_for_status()
    payload = metadata.json()
    repo.stars = int(payload.get("stargazers_count") or 0)
    repo.language = payload.get("language") or repo.language or "Unknown"
    repo.description = payload.get("description") or repo.description

    readme = requests.get(f"{API_ROOT}/repos/{repo.full_name}/readme", headers=_headers(token), timeout=20)
    if readme.ok:
        body = readme.json()
        if body.get("encoding") == "base64" and body.get("content"):
            repo.readme = base64.b64decode(body["content"]).decode("utf-8", errors="replace")
    return repo
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_repository.py -v`

Expected: 2 tests PASS.

```bash
git add src/github_digest/repository.py tests/test_repository.py
git commit -m "feat: enrich trending repositories"
```

### Task 4: Previous-day streak calculation and successful-report persistence

**Files:**
- Create: `src/github_digest/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write failing streak and persistence tests**

```python
# tests/test_history.py
import json
from datetime import date

from github_digest.history import apply_streaks, save_report
from github_digest.models import DailyReport, TrendingRepo


def test_apply_streaks_increments_only_repositories_from_previous_day(tmp_path):
    previous = {
        "report_date": "2026-08-10",
        "repositories": [
            {"full_name": "openai/codex", "streak_days": 3},
            {"full_name": "owner/gone", "streak_days": 2},
        ],
    }
    (tmp_path / "2026-08-10.json").write_text(json.dumps(previous), encoding="utf-8")
    repos = [
        TrendingRepo(rank=1, full_name="openai/codex", url="https://github.com/openai/codex"),
        TrendingRepo(rank=2, full_name="owner/new", url="https://github.com/owner/new"),
    ]
    apply_streaks(repos, report_date=date(2026, 8, 11), history_dir=tmp_path)
    assert repos[0].streak_days == 4
    assert repos[1].streak_days == 1


def test_apply_streaks_resets_after_missing_calendar_day(tmp_path):
    old = {"report_date": "2026-08-09", "repositories": [{"full_name": "openai/codex", "streak_days": 7}]}
    (tmp_path / "2026-08-09.json").write_text(json.dumps(old), encoding="utf-8")
    repo = TrendingRepo(rank=1, full_name="openai/codex", url="https://github.com/openai/codex")
    apply_streaks([repo], report_date=date(2026, 8, 11), history_dir=tmp_path)
    assert repo.streak_days == 1


def test_save_report_writes_utf8_json_and_markdown(tmp_path):
    report = DailyReport(
        report_date="2026-08-11",
        generated_at="2026-08-11T08:00:00+08:00",
        repositories=[TrendingRepo(rank=1, full_name="openai/codex", url="https://github.com/openai/codex", summary_zh="中文摘要")],
    )
    save_report(report, "# GitHub 热榜日报\n\n中文摘要", tmp_path)
    assert "中文摘要" in (tmp_path / "2026-08-11.json").read_text(encoding="utf-8")
    assert "中文摘要" in (tmp_path / "2026-08-11.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_history.py -v`

Expected: FAIL because `github_digest.history` does not exist.

- [ ] **Step 3: Implement adjacent-day lookup and atomic persistence**

```python
# src/github_digest/history.py
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from github_digest.models import DailyReport, TrendingRepo


def apply_streaks(repositories: list[TrendingRepo], report_date: date, history_dir: Path) -> None:
    previous_path = history_dir / f"{report_date - timedelta(days=1):%Y-%m-%d}.json"
    previous_by_name: dict[str, int] = {}
    if previous_path.exists():
        payload = json.loads(previous_path.read_text(encoding="utf-8"))
        previous_by_name = {
            item["full_name"]: int(item.get("streak_days", 1))
            for item in payload.get("repositories", [])
        }
    for repo in repositories:
        repo.streak_days = previous_by_name.get(repo.full_name, 0) + 1


def save_report(report: DailyReport, markdown: str, history_dir: Path) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    json_path = history_dir / f"{report.report_date}.json"
    markdown_path = history_dir / f"{report.report_date}.md"
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_history.py -v`

Expected: 3 tests PASS.

```bash
git add src/github_digest/history.py tests/test_history.py
git commit -m "feat: persist reports and calculate streaks"
```

### Task 5: Multi-provider Chinese summarization fallback

**Files:**
- Create: `src/github_digest/summarizer.py`
- Create: `tests/test_summarizer.py`

- [ ] **Step 1: Write failing provider-order and output-validation tests**

```python
# tests/test_summarizer.py
from github_digest.models import TrendingRepo
from github_digest.summarizer import SummaryResult, summarize_with_fallback


def test_summarizer_uses_first_valid_provider():
    calls = []
    providers = [
        ("Gemini", lambda _: calls.append("Gemini") or SummaryResult("Gemini 摘要", "Gemini")),
        ("GitHub Models", lambda _: calls.append("GitHub Models") or SummaryResult("不应调用", "GitHub Models")),
    ]
    result = summarize_with_fallback(_repo(), providers)
    assert result.text == "Gemini 摘要"
    assert calls == ["Gemini"]


def test_summarizer_falls_through_errors_and_overlong_output():
    def fail(_):
        raise RuntimeError("unavailable")

    providers = [
        ("Gemini", fail),
        ("GitHub Models", lambda _: SummaryResult("太" * 201, "GitHub Models")),
        ("DeepSeek", lambda _: SummaryResult("有效摘要", "DeepSeek")),
    ]
    result = summarize_with_fallback(_repo(), providers)
    assert result == SummaryResult("有效摘要", "DeepSeek")


def test_summarizer_uses_repository_description_when_all_ai_fail():
    result = summarize_with_fallback(_repo(), [("Gemini", lambda _: (_ for _ in ()).throw(RuntimeError()))])
    assert result == SummaryResult("Original description", "repository description")


def _repo():
    return TrendingRepo(
        rank=1,
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description="Original description",
        readme="# Background\nSolves a painful workflow.",
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_summarizer.py -v`

Expected: FAIL because `github_digest.summarizer` does not exist.

- [ ] **Step 3: Implement shared prompt, HTTP providers, validation, and fallback**

```python
# src/github_digest/summarizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import requests

from github_digest.models import TrendingRepo


@dataclass(frozen=True, slots=True)
class SummaryResult:
    text: str
    source: str


Provider = tuple[str, Callable[[TrendingRepo], SummaryResult]]


def build_prompt(repo: TrendingRepo) -> str:
    source = (repo.readme or repo.description)[:12000]
    return (
        "请用不超过200个中文字符介绍下面的GitHub项目。必须清晰覆盖："
        "1.项目背景；2.解决的痛点；3.为什么值得关注。不要使用标题、列表或营销套话。\n"
        f"项目：{repo.full_name}\n仓库简介：{repo.description}\nREADME：{source}"
    )


def _valid(result: SummaryResult) -> bool:
    text = result.text.strip()
    return bool(text) and len(text) <= 200


def summarize_with_fallback(repo: TrendingRepo, providers: list[Provider]) -> SummaryResult:
    for _, provider in providers:
        try:
            result = provider(repo)
            if _valid(result):
                return SummaryResult(result.text.strip(), result.source)
        except (requests.RequestException, RuntimeError, KeyError, ValueError):
            continue
    fallback = repo.description.strip() or f"{repo.full_name} 是今日 GitHub Trending 热门项目。"
    return SummaryResult(fallback[:200], "repository description")


def gemini_provider(api_key: str, model: str = "gemini-2.5-flash") -> Callable[[TrendingRepo], SummaryResult]:
    def summarize(repo: TrendingRepo) -> SummaryResult:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        response = requests.post(
            url,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": build_prompt(repo)}]}]},
            timeout=45,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return SummaryResult(text, "Gemini")
    return summarize


def openai_compatible_provider(
    source: str, endpoint: str, api_key: str, model: str
) -> Callable[[TrendingRepo], SummaryResult]:
    def summarize(repo: TrendingRepo) -> SummaryResult:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": build_prompt(repo)}]},
            timeout=45,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return SummaryResult(text, source)
    return summarize
```

- [ ] **Step 4: Add HTTP-response tests for each provider**

Add these concrete provider HTTP tests to `tests/test_summarizer.py`:

```python
@responses.activate
def test_gemini_provider_parses_generate_content_response():
    responses.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        json={"candidates": [{"content": {"parts": [{"text": "Gemini 中文摘要"}]}}]},
        status=200,
    )
    result = gemini_provider("gemini-key")(_repo())
    assert result == SummaryResult("Gemini 中文摘要", "Gemini")
    assert "key=gemini-key" in responses.calls[0].request.url


@responses.activate
def test_openai_compatible_provider_sends_bearer_token_and_model():
    endpoint = "https://models.github.ai/inference/chat/completions"
    responses.post(endpoint, json={"choices": [{"message": {"content": "GitHub 中文摘要"}}]}, status=200)
    provider = openai_compatible_provider("GitHub Models", endpoint, "github-token", "openai/gpt-4.1-mini")
    result = provider(_repo())
    assert result == SummaryResult("GitHub 中文摘要", "GitHub Models")
    assert responses.calls[0].request.headers["Authorization"] == "Bearer github-token"
    assert b'"model": "openai/gpt-4.1-mini"' in responses.calls[0].request.body
```

Use these concrete OpenAI-compatible endpoints during app assembly:

```python
github_models = openai_compatible_provider(
    "GitHub Models",
    "https://models.github.ai/inference/chat/completions",
    github_token,
    "openai/gpt-4.1-mini",
)
deepseek = openai_compatible_provider(
    "DeepSeek",
    "https://api.deepseek.com/chat/completions",
    deepseek_api_key,
    "deepseek-chat",
)
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_summarizer.py -v`

Expected: all summarizer tests PASS.

```bash
git add src/github_digest/summarizer.py tests/test_summarizer.py
git commit -m "feat: add AI summary fallback chain"
```

### Task 6: Compatible five-card and failure email rendering

**Files:**
- Create: `src/github_digest/renderer.py`
- Create: `src/github_digest/templates/digest.html.j2`
- Create: `src/github_digest/templates/failure.html.j2`
- Create: `tests/test_renderer.py`

- [ ] **Step 1: Write failing rendering assertions**

```python
# tests/test_renderer.py
from github_digest.models import DailyReport, FailureReport, TrendingRepo
from github_digest.renderer import render_digest, render_failure


def test_digest_has_utf8_five_cards_links_and_streak_labels():
    repos = [
        TrendingRepo(
            rank=index,
            full_name=f"owner/repo-{index}",
            url=f"https://github.com/owner/repo-{index}",
            stars=index * 100,
            language="Python",
            streak_days=index,
            summary_zh=f"项目 {index} 的中文摘要",
            summary_source="Gemini",
        )
        for index in range(1, 6)
    ]
    html, markdown = render_digest(DailyReport("2026-08-11", "2026-08-11T08:00:00+08:00", repositories=repos))
    assert '<meta charset="UTF-8">' in html
    assert html.count('data-project-card="true"') == 5
    assert "今日首次上榜" in html
    assert "连续霸榜第 5 天" in html
    assert "项目 5 的中文摘要" in markdown


def test_failure_email_contains_analysis_and_actions_link():
    report = FailureReport(
        generated_at="2026-08-11T08:03:00+08:00",
        stage="Trending fetch",
        attempts=3,
        error="HTTP 503",
        likely_causes=("GitHub 暂时不可用", "Trending 页面结构变化"),
        actions_url="https://github.com/acme/repo/actions/runs/123",
    )
    html = render_failure(report)
    assert "HTTP 503" in html
    assert "重试 3 次" in html
    assert report.actions_url in html
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_renderer.py -v`

Expected: FAIL because `github_digest.renderer` and templates do not exist.

- [ ] **Step 3: Implement renderer entry points**

```python
# src/github_digest/renderer.py
from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape

from github_digest.models import DailyReport, FailureReport


ENV = Environment(
    loader=PackageLoader("github_digest", "templates"),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_digest(report: DailyReport) -> tuple[str, str]:
    if len(report.repositories) != 5:
        raise ValueError("normal digest requires exactly five repositories")
    html = ENV.get_template("digest.html.j2").render(report=report)
    lines = [f"# GitHub 热榜日报 · {report.report_date}", ""]
    for repo in report.repositories:
        streak = "今日首次上榜" if repo.streak_days == 1 else f"连续霸榜第 {repo.streak_days} 天"
        lines.extend([f"## {repo.rank}. [{repo.full_name}]({repo.url})", "", f"{streak} · {repo.language} · ★ {repo.stars}", "", repo.summary_zh, ""])
    return html, "\n".join(lines)


def render_failure(report: FailureReport) -> str:
    return ENV.get_template("failure.html.j2").render(report=report)
```

- [ ] **Step 4: Build the complete email templates**

In `digest.html.j2`, create a full HTML document with `<meta charset="UTF-8">`, a 640px-wide table-based container, inline styles, and this exact card loop contract:

```html
{% for repo in report.repositories %}
<table role="presentation" data-project-card="true" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 12px;background:#ffffff;border:1px solid #d0d7de;border-radius:12px;">
  <tr><td style="padding:16px;font-family:Arial,'Microsoft YaHei',sans-serif;color:#24292f;">
    <div style="font-size:17px;font-weight:700;">{{ repo.rank }}. {{ repo.full_name }} <span style="float:right;color:#9a6700;">★ {{ repo.stars }}</span></div>
    <div style="margin:6px 0 10px;font-size:12px;color:#57606a;">{{ repo.language }} · {% if repo.streak_days == 1 %}今日首次上榜{% else %}连续霸榜第 {{ repo.streak_days }} 天{% endif %}</div>
    <div style="font-size:14px;line-height:1.7;">{{ repo.summary_zh }}</div>
    <div style="margin-top:10px;"><a href="{{ repo.url }}" style="color:#0969da;text-decoration:none;">查看项目 →</a></div>
  </td></tr>
</table>
{% endfor %}
```

Wrap the card loop in `digest.html.j2` with this complete document shell:

```html
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GitHub 热榜日报</title></head>
<body style="margin:0;background:#f6f8fa;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;"><tr><td style="font-family:Arial,'Microsoft YaHei',sans-serif;"><div style="text-align:center;margin-bottom:20px;"><div style="font-size:24px;font-weight:700;color:#24292f;">GitHub 热榜日报</div><div style="font-size:13px;color:#57606a;">{{ report.report_date }} · 全球趋势 Top 5</div></div>
{% for repo in report.repositories %}<table role="presentation" data-project-card="true" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 12px;background:#ffffff;border:1px solid #d0d7de;border-radius:12px;"><tr><td style="padding:16px;font-family:Arial,'Microsoft YaHei',sans-serif;color:#24292f;"><div style="font-size:17px;font-weight:700;">{{ repo.rank }}. {{ repo.full_name }} <span style="float:right;color:#9a6700;">★ {{ repo.stars }}</span></div><div style="margin:6px 0 10px;font-size:12px;color:#57606a;">{{ repo.language }} · {% if repo.streak_days == 1 %}今日首次上榜{% else %}连续霸榜第 {{ repo.streak_days }} 天{% endif %}</div><div style="font-size:14px;line-height:1.7;">{{ repo.summary_zh }}</div><div style="margin-top:10px;"><a href="{{ repo.url }}" style="color:#0969da;text-decoration:none;">查看项目 →</a></div></td></tr></table>{% endfor %}
<div style="text-align:center;font-size:11px;color:#8c959f;margin-top:18px;">由 GitHub Actions 自动生成</div></td></tr></table></td></tr></table></body></html>
```

Create `failure.html.j2` with this complete content:

```html
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GitHub 热榜日报运行异常</title></head><body style="margin:0;background:#fff5f5;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;background:#ffffff;border:1px solid #ff8182;border-radius:12px;"><tr><td style="padding:22px;font-family:Arial,'Microsoft YaHei',sans-serif;color:#24292f;"><h1 style="margin:0 0 12px;color:#cf222e;font-size:22px;">GitHub 热榜日报运行异常</h1><p>执行时间：{{ report.generated_at }}</p><p>失败阶段：{{ report.stage }}</p><p>已重试 {{ report.attempts }} 次</p><p style="padding:12px;background:#ffebe9;border-radius:8px;">{{ report.error }}</p><h2 style="font-size:16px;">可能原因</h2><ul>{% for cause in report.likely_causes %}<li>{{ cause }}</li>{% endfor %}</ul><p><a href="{{ report.actions_url }}" style="color:#0969da;">查看 GitHub Actions 运行记录</a></p></td></tr></table></td></tr></table></body></html>
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_renderer.py -v`

Expected: 2 tests PASS and generated files contain readable Chinese.

```bash
git add src/github_digest/renderer.py src/github_digest/templates tests/test_renderer.py
git commit -m "feat: render digest and failure emails"
```

### Task 7: Gmail SMTP delivery to one or many recipients

**Files:**
- Create: `src/github_digest/mailer.py`
- Create: `tests/test_mailer.py`

- [ ] **Step 1: Write a failing SMTP envelope test**

```python
# tests/test_mailer.py
from unittest.mock import MagicMock, patch

from github_digest.mailer import send_html_email


@patch("github_digest.mailer.smtplib.SMTP_SSL")
def test_send_html_email_uses_all_recipients(mock_smtp):
    client = MagicMock()
    mock_smtp.return_value.__enter__.return_value = client
    send_html_email(
        username="sender@gmail.com",
        app_password="secret",
        recipients=("one@qq.com", "two@bigo.sg"),
        subject="GitHub 热榜日报",
        html="<html><body>中文</body></html>",
    )
    client.login.assert_called_once_with("sender@gmail.com", "secret")
    message = client.send_message.call_args.args[0]
    assert message["To"] == "one@qq.com, two@bigo.sg"
    html_part = message.get_payload()[1]
    assert html_part.get_content_subtype() == "html"
    assert html_part.get_content_charset() == "utf-8"
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_mailer.py -v`

Expected: FAIL because `github_digest.mailer` does not exist.

- [ ] **Step 3: Implement Gmail SMTP delivery**

```python
# src/github_digest/mailer.py
from __future__ import annotations

import smtplib
from email.message import EmailMessage


def send_html_email(
    username: str,
    app_password: str,
    recipients: tuple[str, ...],
    subject: str,
    html: str,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = ", ".join(recipients)
    message.set_content("请使用支持 HTML 的邮件客户端查看本日报。", charset="utf-8")
    message.add_alternative(html, subtype="html", charset="utf-8")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as client:
        client.login(username, app_password)
        client.send_message(message)
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_mailer.py -v`

Expected: 1 test PASS.

```bash
git add src/github_digest/mailer.py tests/test_mailer.py
git commit -m "feat: send digest through Gmail SMTP"
```

### Task 8: Orchestrate normal and failure paths

**Files:**
- Create: `src/github_digest/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing end-to-end orchestration tests**

```python
# tests/test_app.py
from pathlib import Path

import pytest

from github_digest.app import run
from github_digest.config import Config
from github_digest.models import TrendingRepo


def config(tmp_path):
    return Config(
        gmail_username="sender@gmail.com",
        gmail_app_password="secret",
        recipients=("one@qq.com", "two@bigo.sg"),
        gemini_api_key="gemini",
        deepseek_api_key="deepseek",
        github_token="github",
        history_dir=str(tmp_path),
    )


def test_run_sends_normal_digest_then_saves_history(monkeypatch, tmp_path):
    events = []
    repos = [TrendingRepo(index, f"owner/repo-{index}", f"https://github.com/owner/repo-{index}", description="desc") for index in range(1, 6)]
    monkeypatch.setattr("github_digest.app.fetch_trending", lambda top_count: repos)
    monkeypatch.setattr("github_digest.app.enrich_repository", lambda repo, token: repo)
    monkeypatch.setattr("github_digest.app.summarize_repository", lambda repo, cfg: ("中文摘要", "Gemini"))
    monkeypatch.setattr("github_digest.app.send_html_email", lambda **kwargs: events.append("sent"))
    monkeypatch.setattr("github_digest.app.save_report", lambda *args: events.append("saved"))
    assert run(config(tmp_path)) == 0
    assert events == ["sent", "saved"]


def test_run_sends_failure_email_and_does_not_save_history(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr("github_digest.app.fetch_trending", lambda top_count: (_ for _ in ()).throw(RuntimeError("HTTP 503")))
    monkeypatch.setattr("github_digest.app.send_html_email", lambda **kwargs: events.append(kwargs["subject"]))
    monkeypatch.setattr("github_digest.app.save_report", lambda *args: events.append("saved"))
    assert run(config(tmp_path)) == 1
    assert events == ["GitHub 热榜日报运行异常"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_app.py -v`

Expected: FAIL because `github_digest.app` does not exist.

- [ ] **Step 3: Implement the orchestration entry point**

```python
# src/github_digest/app.py
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from github_digest.config import Config, load_config
from github_digest.history import apply_streaks, save_report
from github_digest.mailer import send_html_email
from github_digest.models import DailyReport, FailureReport, TrendingRepo
from github_digest.renderer import render_digest, render_failure
from github_digest.repository import enrich_repository
from github_digest.summarizer import gemini_provider, openai_compatible_provider, summarize_with_fallback
from github_digest.trending import fetch_trending


LOGGER = logging.getLogger(__name__)


def summarize_repository(repo: TrendingRepo, config: Config) -> tuple[str, str]:
    providers = [
        ("Gemini", gemini_provider(config.gemini_api_key)),
        ("GitHub Models", openai_compatible_provider("GitHub Models", "https://models.github.ai/inference/chat/completions", config.github_token, "openai/gpt-4.1-mini")),
        ("DeepSeek", openai_compatible_provider("DeepSeek", "https://api.deepseek.com/chat/completions", config.deepseek_api_key, "deepseek-chat")),
    ]
    result = summarize_with_fallback(repo, providers)
    return result.text, result.source


def _actions_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repository = os.getenv("GITHUB_REPOSITORY", "unknown/unknown")
    run_id = os.getenv("GITHUB_RUN_ID", "unknown")
    return f"{server}/{repository}/actions/runs/{run_id}"


def run(config: Config) -> int:
    now = datetime.now(ZoneInfo(config.timezone))
    try:
        repositories = fetch_trending(config.top_count)
        enriched: list[TrendingRepo] = []
        for repo in repositories:
            try:
                enriched.append(enrich_repository(repo, config.github_token))
            except Exception:
                LOGGER.warning("repository enrichment failed for %s", repo.full_name, exc_info=True)
                enriched.append(repo)
        repositories = enriched
        apply_streaks(repositories, now.date(), Path(config.history_dir))
        for repo in repositories:
            repo.summary_zh, repo.summary_source = summarize_repository(repo, config)
        report = DailyReport(now.date().isoformat(), now.isoformat(), repositories=repositories)
        html, markdown = render_digest(report)
        send_html_email(
            username=config.gmail_username,
            app_password=config.gmail_app_password,
            recipients=config.recipients,
            subject=f"GitHub 热榜日报 · {report.report_date}",
            html=html,
        )
        save_report(report, markdown, Path(config.history_dir))
        return 0
    except Exception as exc:
        LOGGER.exception("digest generation failed")
        failure = FailureReport(
            generated_at=now.isoformat(),
            stage="GitHub Trending or digest generation",
            attempts=3,
            error=str(exc)[:500],
            likely_causes=("GitHub 网络或限流异常", "Trending 页面结构变化", "外部服务暂时不可用"),
            actions_url=_actions_url(),
        )
        send_html_email(
            username=config.gmail_username,
            app_password=config.gmail_app_password,
            recipients=config.recipients,
            subject="GitHub 热榜日报运行异常",
            html=render_failure(failure),
        )
        return 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(run(load_config()))
```

- [ ] **Step 4: Add a mailer-failure test**

Add a test proving that if both normal processing and the failure email's SMTP send fail, `run()` raises the SMTP exception so GitHub Actions ends in failure and retains the traceback in logs.

```python
def test_run_surfaces_failure_when_alert_email_also_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("github_digest.app.fetch_trending", lambda top_count: (_ for _ in ()).throw(RuntimeError("parse failed")))
    monkeypatch.setattr("github_digest.app.send_html_email", lambda **kwargs: (_ for _ in ()).throw(ConnectionError("smtp failed")))
    with pytest.raises(ConnectionError, match="smtp failed"):
        run(config(tmp_path))
```

- [ ] **Step 5: Run the entire suite and commit**

Run: `python -m pytest -v`

Expected: all tests PASS.

```bash
git add src/github_digest/app.py tests/test_app.py
git commit -m "feat: orchestrate daily digest workflow"
```

### Task 9: GitHub Actions schedule, history commit, and operator documentation

**Files:**
- Create: `.github/workflows/daily-digest.yml`
- Create: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Add generated and local-secret exclusions**

Append these lines to `.gitignore` while keeping `.superpowers/`:

```gitignore
.venv/
__pycache__/
.pytest_cache/
*.pyc
.env
```

- [ ] **Step 2: Create the scheduled and manual workflow**

```yaml
# .github/workflows/daily-digest.yml
name: GitHub Trending Daily Digest

on:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

permissions:
  contents: write
  models: read

concurrency:
  group: github-trending-daily
  cancel-in-progress: false

jobs:
  send-digest:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: python -m pip install -e '.[test]'

      - name: Test
        run: python -m pytest -q

      - name: Generate and send digest
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          GMAIL_USERNAME: ${{ secrets.GMAIL_USERNAME }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
        run: github-trending-digest

      - name: Commit successful report history
        if: success()
        run: |
          if git diff --quiet -- reports/history; then
            echo "No report history changes"
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add reports/history
          git commit -m "chore: add trending digest $(date -u +%F)"
          git push
```

- [ ] **Step 3: Write setup and operations documentation**

Create `README.md` with these exact sections and commands:

````markdown
# GitHub Trending Daily Digest

每天北京时间 08:00 获取 GitHub Daily Trending 全球前五，生成中文卡片日报并通过 Gmail 发送。

## Required GitHub Secrets

- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`
- `GMAIL_USERNAME`
- `GMAIL_APP_PASSWORD`：Google 账号开启两步验证后创建的应用专用密码
- `MAIL_TO`：单个邮箱或英文逗号分隔的多个邮箱，例如 `wangyaoyi@bigo.sg,user@qq.com`

## Local verification

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -v
```

## First run

在仓库的 Actions 页面打开 `GitHub Trending Daily Digest`，选择 `Run workflow`。确认邮件送达且 `reports/history/YYYY-MM-DD.json` 与 `.md` 被提交。

## Troubleshooting

- 没收到邮件：检查垃圾邮件、Gmail 应用专用密码和 `MAIL_TO`。
- AI 摘要降级：查看 Action 日志中的 provider 名称，不要打印 API Key。
- Trending 失败：异常日报会附带本次 Actions 运行链接；若邮件也失败，直接查看 Actions 日志。
````

- [ ] **Step 4: Validate workflow syntax, run tests, and inspect secrets safety**

Run:

```bash
python -m pytest -v
python -c "import yaml; yaml.safe_load(open('.github/workflows/daily-digest.yml'))" || true
rg -n "(AIza|sk-|app-password|secret)" --glob '!docs/superpowers/**' .
git diff --check
```

Expected:

- All tests PASS.
- Workflow parses when PyYAML is available; otherwise the optional parse command exits through `|| true`.
- Secret scan finds only test dummy strings, never real credentials.
- `git diff --check` emits no output.

- [ ] **Step 5: Commit workflow and documentation**

```bash
git add .github/workflows/daily-digest.yml README.md .gitignore
git commit -m "ci: schedule and document daily digest"
```

### Task 10: Final verification and a safe manual-run checklist

**Files:**
- Verify: all project files
- Verify after first GitHub run: `reports/history/YYYY-MM-DD.json`
- Verify after first GitHub run: `reports/history/YYYY-MM-DD.md`

- [ ] **Step 1: Run the complete local verification suite**

Run:

```bash
python -m pip install -e '.[test]'
python -m pytest -v
git diff --check
git status --short
```

Expected: all tests PASS, no whitespace errors, and only intentionally uncommitted files appear.

- [ ] **Step 2: Review the generated HTML locally without sending email**

Run:

```bash
python - <<'PY'
from pathlib import Path
from github_digest.models import DailyReport, TrendingRepo
from github_digest.renderer import render_digest

repos = [TrendingRepo(i, f"owner/repo-{i}", f"https://github.com/owner/repo-{i}", stars=i*100, language="Python", streak_days=i, summary_zh=f"项目 {i} 中文摘要") for i in range(1, 6)]
html, _ = render_digest(DailyReport("2026-08-11", "2026-08-11T08:00:00+08:00", repositories=repos))
Path("/tmp/github-trending-digest-preview.html").write_text(html, encoding="utf-8")
print("/tmp/github-trending-digest-preview.html")
PY
```

Open `/tmp/github-trending-digest-preview.html` in a browser and verify five light vertical cards, readable Chinese, working links, and mobile-width behavior.

- [ ] **Step 3: Configure repository Secrets**

In GitHub repository Settings → Secrets and variables → Actions, add:

```text
GEMINI_API_KEY
DEEPSEEK_API_KEY
GMAIL_USERNAME
GMAIL_APP_PASSWORD
MAIL_TO
```

Set `MAIL_TO` to one address for the first smoke test. After success, change it to two addresses separated by an English comma and run again.

- [ ] **Step 4: Trigger the workflow manually and verify delivery**

Expected:

- Every configured recipient receives the same subject and five-card HTML body.
- Chinese renders correctly in Gmail and at least one non-Gmail recipient such as QQ or the company mailbox.
- The workflow commits one JSON and one Markdown history file only after email delivery succeeds.
- A second-day fixture or controlled history test shows `连续霸榜第 2 天`.

- [ ] **Step 5: Exercise the failure-analysis path without exposing secrets**

Run the deterministic failure-path tests instead of modifying production behavior:

```bash
python -m pytest tests/test_trending.py::test_fetch_trending_retries_three_times_then_fails tests/test_app.py::test_run_sends_failure_email_and_does_not_save_history tests/test_renderer.py::test_failure_email_contains_analysis_and_actions_link -v
```

Expected: all three tests PASS and collectively verify three retries, failure-email delivery, no history save, concise error analysis, and the Actions URL.

- [ ] **Step 6: Commit any verification-only fixes**

```bash
git add -A
git commit -m "test: verify daily digest end to end"
```

If verification required no changes, do not create an empty commit.
