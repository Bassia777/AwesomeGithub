from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup

from github_digest.models import DailyReport, FailureReport, TrendingRepo
from github_digest.renderer import render_digest, render_failure


def _report() -> DailyReport:
    repositories = [
        TrendingRepo(
            rank=index,
            full_name=f"owner/project-{index}",
            url=f"https://github.com/owner/project-{index}",
            language="Python" if index < 5 else "Rust",
            stars=1000 * index,
            streak_days=1 if index == 1 else index,
            summary_zh=f"这是第 {index} 个项目的中文摘要，解决实际开发问题。",
        )
        for index in range(1, 6)
    ]
    return DailyReport(
        report_date="2026-08-11",
        generated_at="2026-08-11T08:00:00+00:00",
        repositories=repositories,
    )


def test_render_digest_renders_five_utf8_cards_and_markdown() -> None:
    report = _report()

    html, markdown = render_digest(report)

    assert '<html lang="zh-CN">' in html
    assert '<meta charset="UTF-8">' in html
    assert html.count('data-project-card="true"') == 5
    assert "GitHub Trending 全球 Top 5" in html
    assert report.report_date in html
    assert "今日首次上榜" in html
    assert "连续霸榜第 5 天" in html
    for repository in report.repositories:
        assert repository.full_name in html
        assert repository.summary_zh in html
        assert f'href="{repository.url}"' in html
        assert repository.full_name.replace("/", r"\/").replace("-", r"\-") in markdown
        assert repository.summary_zh in markdown
        assert repository.url in markdown
    assert "# GitHub Trending 全球 Top 5" in markdown
    assert "2026-08-11" in markdown
    assert "今日首次上榜" in markdown
    assert "连续霸榜第 5 天" in markdown
    assert "�" not in html
    assert "�" not in markdown


def test_render_digest_uses_five_independent_table_cards() -> None:
    html, _ = render_digest(_report())

    document = BeautifulSoup(html, "html.parser")
    cards = document.select('table[role="presentation"][data-project-card="true"]')

    assert len(cards) == 5
    assert document.find("h1", string="GitHub Trending 全球 Top 5")
    assert len(document.find_all("h2")) == 5
    for card in cards:
        assert "background:" in card["style"]
        assert "border:" in card["style"]
        assert "margin:" not in card["style"]
        assert not card.select('table[data-project-card="true"]')
        assert "padding:" in card.find("td")["style"]
        assert "padding-bottom:" in card.parent["style"]


def test_render_digest_autoescapes_text_and_blocks_unsafe_href() -> None:
    report = _report()
    malicious = report.repositories[0]
    malicious.full_name = '<img src=x onerror="alert(1)">'
    malicious.summary_zh = '<script>alert("xss")</script> 中文摘要'
    malicious.url = "javascript:alert(1)"

    html, markdown = render_digest(report)

    assert '<img src=x onerror="alert(1)">' not in html
    assert '&lt;img src=x onerror=&#34;alert(1)&#34;&gt;' in html
    assert '<script>alert("xss")</script>' not in html
    assert '&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt; 中文摘要' in html
    assert 'href="javascript:alert(1)"' not in html
    assert 'href="#"' not in html
    assert "javascript:alert(1)" not in markdown
    assert not re.search(r"(?<!\\)<img src=x onerror", markdown)
    assert r'\<img src\=x onerror\=\"alert\(1\)\"\>' in markdown


def test_render_digest_neutralizes_hostile_markdown_and_html() -> None:
    report = _report()
    malicious = report.repositories[0]
    malicious.full_name = "owner/repo\r\n# injected heading ![image](https://evil.example/image.png)"
    malicious.language = "Python\n## injected language"
    malicious.summary_zh = (
        "<img src=x onerror=alert(1)>\r\n"
        "[injected link](javascript:alert(1)) ![image](https://evil.example/image.png)"
    )
    malicious.url = "https://evil.example/owner/repo"

    _, markdown = render_digest(report)

    assert "https://evil.example/owner/repo" not in markdown
    assert "\n# injected heading" not in markdown
    assert "\n## injected language" not in markdown
    assert not re.search(r"(?<!\\)<img src=x", markdown)
    assert "![image](https://evil.example/image.png)" not in markdown
    assert "[injected link](javascript:alert(1))" not in markdown
    assert r"\<img src\=x onerror\=alert\(1\)\>" in markdown
    assert r"\[injected link\]\(javascript\:alert\(1\)\)" in markdown


def test_render_digest_escapes_fences_tildes_and_all_ascii_punctuation() -> None:
    report = _report()
    report.repositories[0].summary_zh = "~~~html\n```html\n`code` ~ tilde !@#$%^&*_-+=|:;,.?/\\"

    _, markdown = render_digest(report)

    assert "\n~~~html" not in markdown
    assert "\n```html" not in markdown
    assert r"\~\~\~html" in markdown
    assert r"\`\`\`html" in markdown
    assert r"\`code\`" in markdown
    assert r"\!\@\#\$\%\^\&\*\_\-\+\=\|\:\;\,\.\?\/\\" in markdown


@pytest.mark.parametrize("report_date", ["2026-8-11", "2026-02-30", "2026-08-11\n# heading"])
def test_render_digest_rejects_noncanonical_report_date(report_date: str) -> None:
    report = _report()
    report.report_date = report_date

    with pytest.raises(ValueError, match="report.report_date"):
        render_digest(report)


def test_render_digest_derives_canonical_link_from_matching_full_name() -> None:
    report = _report()
    report.repositories[0].full_name = "OpenAI/Codex"
    report.repositories[0].url = "https://github.com/openai/codex"

    html, markdown = render_digest(report)

    assert 'href="https://github.com/OpenAI/Codex"' in html
    assert "[OpenAI\\/Codex](https://github.com/OpenAI/Codex)" in markdown


@pytest.mark.parametrize(
    ("full_name", "url"),
    [
        ("owner/repo", "https://github.com/other/repo"),
        ("-owner/repo", "https://github.com/-owner/repo"),
        ("owner-/repo", "https://github.com/owner-/repo"),
        ("owner/.", "https://github.com/owner/."),
        ("owner/..", "https://github.com/owner/.."),
        ("owner/repo", "https://user@github.com/owner/repo"),
        ("owner/repo", "https://github.com:443/owner/repo"),
        ("owner/repo", "https://github.com/owner/repo/extra"),
        ("owner/repo", "https://github.com/owner/repo?query=value"),
    ],
)
def test_render_digest_omits_links_for_noncanonical_repository_identity(
    full_name: str, url: str
) -> None:
    report = _report()
    report.repositories[0].full_name = full_name
    report.repositories[0].url = url

    html, markdown = render_digest(report)

    first_card = BeautifulSoup(html, "html.parser").select('[data-project-card="true"]')[0]
    assert not first_card.find("a")
    assert url not in markdown


def test_render_digest_requires_exactly_five_repositories() -> None:
    report = _report()
    report.repositories.pop()

    with pytest.raises(ValueError, match="exactly 5"):
        render_digest(report)


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("rank", 0, "rank"),
        ("rank", True, "rank"),
        ("stars", -1, "stars"),
        ("stars", "many", "stars"),
        ("streak_days", 0, "streak_days"),
        ("streak_days", 1.5, "streak_days"),
    ],
)
def test_render_digest_rejects_malformed_numeric_repository_values(
    attribute: str, value: object, message: str
) -> None:
    report = _report()
    setattr(report.repositories[0], attribute, value)

    with pytest.raises(ValueError, match=message):
        render_digest(report)


@pytest.mark.parametrize("ranks", [[1, 2, 2, 4, 5], [2, 1, 3, 4, 5]])
def test_render_digest_requires_ordered_unique_top_five_ranks(ranks: list[int]) -> None:
    report = _report()
    for repository, rank in zip(report.repositories, ranks, strict=True):
        repository.rank = rank

    with pytest.raises(ValueError, match="ranks"):
        render_digest(report)


def test_render_failure_renders_safe_full_email() -> None:
    failure = FailureReport(
        generated_at="2026-08-11T09:00:00+00:00",
        stage="发送邮件",
        attempts=2,
        error='<script>alert("secret")</script>',
        likely_causes=("网络超时", '<img src=x onerror="alert(1)">'),
        actions_url="https://github.com/example/repo/actions/runs/123",
    )

    html = render_failure(failure)

    assert '<html lang="zh-CN">' in html
    assert '<meta charset="UTF-8">' in html
    assert "执行失败" in html
    assert "2026-08-11T09:00:00+00:00" in html
    assert "发送邮件" in html
    assert "已重试 2 次" in html
    assert "网络超时" in html
    assert 'href="https://github.com/example/repo/actions/runs/123"' in html
    assert '<script>alert("secret")</script>' not in html
    assert '&lt;script&gt;alert(&#34;secret&#34;)&lt;/script&gt;' in html
    assert '<img src=x onerror="alert(1)">' not in html
    assert '&lt;img src=x onerror=&#34;alert(1)&#34;&gt;' in html
    assert "�" not in html
    document = BeautifulSoup(html, "html.parser")
    assert document.find("h1", string="GitHub Trending Digest 执行失败")
    assert document.find("h2", string="建议检查项")
    assert "GitHub 网络与速率限制" in html
    assert "Trending 页面结构" in html
    assert "外部摘要服务状态" in html
    assert "Secrets/SMTP 配置" in html


@pytest.mark.parametrize(
    "actions_url",
    [
        "javascript:alert(1)",
        "https://github.com/owner/repo/actions/runs/not-a-number",
        "https://github.com/owner/repo/issues/123",
        "https://evil.example/owner/repo/actions/runs/123",
        "https://[malformed",
    ],
)
def test_render_failure_hides_invalid_actions_links(actions_url: str) -> None:
    failure = FailureReport(
        generated_at="2026-08-11T09:00:00+00:00",
        stage="发送邮件",
        attempts=2,
        error="SMTP unavailable",
        likely_causes=("网络超时",),
        actions_url=actions_url,
    )

    html = render_failure(failure)

    document = BeautifulSoup(html, "html.parser")
    assert "Actions 运行链接不可用" in document.get_text()
    assert not document.find("a")


@pytest.mark.parametrize(
    "actions_url",
    [
        "https://github.com/owner/repo/actions/runs/0",
        "https://github.com/-owner/repo/actions/runs/1",
        "https://github.com/owner/../repo/actions/runs/1",
        "https://github.com/owner/repo/actions/runs/1?query=value",
        "https://user@github.com/owner/repo/actions/runs/1",
        "https://github.com:443/owner/repo/actions/runs/1",
    ],
)
def test_render_failure_rejects_noncanonical_actions_identity(actions_url: str) -> None:
    failure = FailureReport(
        generated_at="2026-08-11T09:00:00+00:00",
        stage="发送邮件",
        attempts=2,
        error="SMTP unavailable",
        likely_causes=("网络超时",),
        actions_url=actions_url,
    )

    html = render_failure(failure)

    assert "Actions 运行链接不可用" in BeautifulSoup(html, "html.parser").get_text()


@pytest.mark.parametrize("attempts", [0, -1, True, "two"])
def test_render_failure_rejects_invalid_attempt_count(attempts: object) -> None:
    failure = FailureReport(
        generated_at="2026-08-11T09:00:00+00:00",
        stage="发送邮件",
        attempts=attempts,
        error="SMTP unavailable",
        likely_causes=("网络超时",),
        actions_url="https://github.com/owner/repo/actions/runs/1",
    )

    with pytest.raises(ValueError, match="attempts"):
        render_failure(failure)
