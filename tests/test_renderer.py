from __future__ import annotations

import re

import pytest

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
        assert repository.full_name in markdown
        assert repository.summary_zh in markdown
        assert repository.url in markdown
    assert "# GitHub Trending 全球 Top 5" in markdown
    assert "2026-08-11" in markdown
    assert "今日首次上榜" in markdown
    assert "连续霸榜第 5 天" in markdown
    assert "�" not in html
    assert "�" not in markdown


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
    assert 'href="#"' in html
    assert "javascript:alert(1)" not in markdown
    assert re.search(r"\[<img src=x onerror=\"alert\(1\)\">\]\(#\)", markdown)


def test_render_digest_requires_exactly_five_repositories() -> None:
    report = _report()
    report.repositories.pop()

    with pytest.raises(ValueError, match="exactly 5"):
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
