from __future__ import annotations

from typing import get_type_hints

from github_digest.models import DailyReport, FailureReport, TrendingRepo


def test_daily_report_uses_string_timestamps_and_serializes_repositories() -> None:
    report = DailyReport(
        report_date="2026-08-11",
        generated_at="2026-08-11T09:00:00+08:00",
        repositories=[TrendingRepo(rank=1, full_name="owner/repo", url="https://example.com")],
    )

    assert get_type_hints(DailyReport)["report_date"] is str
    assert get_type_hints(DailyReport)["generated_at"] is str
    assert report.to_dict()["report_date"] == "2026-08-11"
    assert report.to_dict()["generated_at"] == "2026-08-11T09:00:00+08:00"
    assert report.to_dict()["repositories"] == [
        {
            "rank": 1,
            "full_name": "owner/repo",
            "url": "https://example.com",
            "description": "",
            "language": "Unknown",
            "stars": 0,
            "readme": "",
            "streak_days": 1,
            "summary_zh": "",
            "summary_source": "",
        }
    ]


def test_failure_report_uses_a_string_timestamp() -> None:
    assert get_type_hints(FailureReport)["generated_at"] is str
