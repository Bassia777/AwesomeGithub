from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("invalid_streak", [True, 1.5, None, 0, -1])
def test_apply_streaks_defaults_non_positive_or_non_integer_streaks_to_one(
    tmp_path: Path, invalid_streak: object
) -> None:
    _write_history(
        tmp_path,
        "2026-08-10",
        [{"full_name": "openai/codex", "streak_days": invalid_streak}],
    )
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 2


def test_apply_streaks_uses_largest_valid_streak_for_duplicate_history_entries(
    tmp_path: Path,
) -> None:
    _write_history(
        tmp_path,
        "2026-08-10",
        [
            {"full_name": "openai/codex", "streak_days": 5},
            {"full_name": "openai/codex", "streak_days": 2},
            {"full_name": "openai/codex", "streak_days": "7"},
        ],
    )
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 6


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


@pytest.mark.parametrize("payload", [[], {"repositories": {}}, {"not_repositories": []}])
def test_apply_streaks_ignores_valid_json_with_wrong_shape(tmp_path: Path, payload: object) -> None:
    (tmp_path / "2026-08-10.json").write_text(json.dumps(payload), encoding="utf-8")
    repositories = [_repository("openai/codex")]

    apply_streaks(repositories, date(2026, 8, 11), tmp_path)

    assert repositories[0].streak_days == 1


def test_apply_streaks_propagates_permission_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history_file = tmp_path / "2026-08-10.json"
    history_file.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def raise_permission_error(path: Path, *args: object, **kwargs: object) -> str:
        if path == history_file:
            raise PermissionError("denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raise_permission_error)

    with pytest.raises(PermissionError, match="denied"):
        apply_streaks([_repository("openai/codex")], date(2026, 8, 11), tmp_path)


def test_save_report_writes_utf8_json_and_markdown_with_single_trailing_newline(
    tmp_path: Path,
) -> None:
    report = DailyReport(
        report_date="2026-08-11",
        generated_at="2026-08-11T08:00:00+00:00",
        repositories=[_repository("openai/codex")],
    )
    report.repositories[0].summary_zh = "适合构建智能编程工作流。"

    save_report(report, "# 今日趋势\n\n中文摘要\r\n", tmp_path)

    json_contents = (tmp_path / "2026-08-11.json").read_text(encoding="utf-8")
    markdown_contents = (tmp_path / "2026-08-11.md").read_text(encoding="utf-8")
    assert json_contents == json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    assert json.loads(json_contents) == report.to_dict()
    assert "适合构建智能编程工作流。" in json_contents
    assert markdown_contents == "# 今日趋势\n\n中文摘要\n"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    "report_date",
    ["2026-8-11", "2026-08-11T00:00:00", "2026/08/11", "../2026-08-11", "not-a-date"],
)
def test_save_report_rejects_noncanonical_report_dates(tmp_path: Path, report_date: str) -> None:
    report = DailyReport(report_date=report_date, generated_at="2026-08-11T08:00:00+00:00")

    with pytest.raises(ValueError, match="report_date"):
        save_report(report, "# report", tmp_path / "history")

    assert not (tmp_path / "history").exists()


def test_save_report_rolls_back_new_json_when_markdown_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_dir = tmp_path / "history"
    report = DailyReport(report_date="2026-08-11", generated_at="2026-08-11T08:00:00+00:00")
    markdown_path = history_dir / "2026-08-11.md"
    original_replace = Path.replace

    def fail_markdown_replace(path: Path, target: Path) -> Path:
        if Path(target) == markdown_path:
            raise OSError("markdown publish failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_markdown_replace)

    with pytest.raises(OSError, match="markdown publish failed"):
        save_report(report, "# report", history_dir)

    assert not (history_dir / "2026-08-11.json").exists()
    assert not markdown_path.exists()
    assert not list(history_dir.glob(".*"))


def test_save_report_restores_existing_json_when_markdown_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    json_path = history_dir / "2026-08-11.json"
    markdown_path = history_dir / "2026-08-11.md"
    json_path.write_text('{"old": true}\n', encoding="utf-8")
    markdown_path.write_text("old markdown\n", encoding="utf-8")
    report = DailyReport(report_date="2026-08-11", generated_at="2026-08-11T08:00:00+00:00")
    original_replace = Path.replace

    def fail_markdown_replace(path: Path, target: Path) -> Path:
        if Path(target) == markdown_path:
            raise OSError("markdown publish failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_markdown_replace)

    with pytest.raises(OSError, match="markdown publish failed"):
        save_report(report, "# report", history_dir)

    assert json_path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert markdown_path.read_text(encoding="utf-8") == "old markdown\n"
    assert not list(history_dir.glob(".*"))
