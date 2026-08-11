from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from github_digest.history import apply_streaks, save_report
from github_digest.models import DailyReport, TrendingRepo


def _repository(full_name: str, streak_days: int = 1) -> TrendingRepo:
    return TrendingRepo(
        rank=1,
        full_name=full_name,
        url=f"https://github.com/{full_name}",
        streak_days=streak_days,
    )


def _write_history(history_dir: Path, report_date: str, repositories: object) -> None:
    history_dir.mkdir(exist_ok=True)
    (history_dir / f"{report_date}.json").write_text(
        json.dumps({"repositories": repositories}), encoding="utf-8"
    )


def test_apply_streaks_increments_exact_previous_day_match(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        "2026-08-10",
        [{"full_name": "openai/codex", "streak_days": 3}],
    )
    repositories = [_repository("openai/codex"), _repository("new/project")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert [repository.streak_days for repository in repositories] == [4, 1]


def test_apply_streaks_does_not_cross_a_gap_day(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        "2026-08-09",
        [{"full_name": "openai/codex", "streak_days": 3}],
    )
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 1


def test_apply_streaks_uses_case_sensitive_canonical_full_name(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        "2026-08-10",
        [{"full_name": "OpenAI/Codex", "streak_days": 3}],
    )
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 1


def test_apply_streaks_defaults_invalid_previous_data_to_one(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        "2026-08-10",
        [
            {"full_name": "missing/streak"},
            {"full_name": "zero/streak", "streak_days": 0},
            {"full_name": "negative/streak", "streak_days": -5},
            {"full_name": "bad/streak", "streak_days": "three"},
            {"streak_days": 9},
            "not a repository",
        ],
    )
    repositories = [
        _repository("missing/streak"),
        _repository("zero/streak"),
        _repository("negative/streak"),
        _repository("bad/streak"),
    ]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert [repository.streak_days for repository in repositories] == [2, 2, 2, 2]


def test_apply_streaks_ignores_malformed_previous_json(tmp_path: Path) -> None:
    (tmp_path / "2026-08-10.json").write_text("not JSON", encoding="utf-8")
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 1


def test_apply_streaks_ignores_non_utf8_previous_json(tmp_path: Path) -> None:
    (tmp_path / "2026-08-10.json").write_bytes(b"\xff")
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 1


def test_save_report_writes_utf8_json_and_markdown_with_single_trailing_newline(
    tmp_path: Path,
) -> None:
    report = DailyReport(
        report_date="2026-08-11",
        generated_at="2026-08-11T08:00:00+00:00",
        repositories=[_repository("openai/codex")],
    )

    save_report(report, "# 今日趋势\n\n中文摘要", tmp_path)

    json_contents = (tmp_path / "2026-08-11.json").read_text(encoding="utf-8")
    markdown_contents = (tmp_path / "2026-08-11.md").read_text(encoding="utf-8")
    assert json_contents == json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    assert json.loads(json_contents) == report.to_dict()
    assert markdown_contents == "# 今日趋势\n\n中文摘要\n"
