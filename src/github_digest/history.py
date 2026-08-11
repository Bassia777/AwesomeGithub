"""Persistence and streak calculations for daily digest reports."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from github_digest.models import DailyReport, TrendingRepo


def apply_streaks(
    repositories: Iterable[TrendingRepo], report_date: date, history_dir: Path
) -> None:
    """Set each repository's streak from the immediately preceding report."""
    previous_path = history_dir / f"{report_date - timedelta(days=1):%Y-%m-%d}.json"
    previous_streaks = _read_streaks(previous_path)

    for repository in repositories:
        full_name = getattr(repository, "full_name", None)
        if not isinstance(full_name, str):
            continue
        previous_streak = previous_streaks.get(full_name, 0)
        repository.streak_days = previous_streak + 1 if previous_streak > 0 else 1


def save_report(report: DailyReport, markdown: str, history_dir: Path) -> None:
    """Atomically persist a successfully generated report as JSON and Markdown."""
    history_dir.mkdir(parents=True, exist_ok=True)
    report_date = report.report_date
    json_content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown_content = markdown.rstrip("\n") + "\n"
    _atomic_write(history_dir / f"{report_date}.json", json_content)
    _atomic_write(history_dir / f"{report_date}.md", markdown_content)


def _read_streaks(path: Path) -> dict[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("repositories"), list):
        return {}

    streaks: dict[str, int] = {}
    for repository in payload["repositories"]:
        if not isinstance(repository, dict):
            continue
        full_name = repository.get("full_name")
        if not isinstance(full_name, str):
            continue
        streak_days = repository.get("streak_days", 1)
        if not isinstance(streak_days, int) or isinstance(streak_days, bool) or streak_days <= 0:
            streak_days = 1
        streaks[full_name] = streak_days
    return streaks


def _atomic_write(path: Path, content: str) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
