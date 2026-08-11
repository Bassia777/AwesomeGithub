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
    """Atomically persist a successfully generated report as JSON and Markdown pair."""
    report_date = _validate_report_date(report.report_date)
    json_path, markdown_path = _report_paths(history_dir, report_date)
    json_content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown_content = markdown.rstrip("\r\n") + "\n"
    history_dir.mkdir(parents=True, exist_ok=True)

    temporary_paths: list[Path] = []
    json_published = False
    json_backup: Path | None = None
    try:
        json_temporary = _stage_text(json_path, json_content)
        markdown_temporary = _stage_text(markdown_path, markdown_content)
        temporary_paths.extend((json_temporary, markdown_temporary))
        json_backup = _stage_existing_file(json_path)
        if json_backup is not None:
            temporary_paths.append(json_backup)

        json_temporary.replace(json_path)
        temporary_paths.remove(json_temporary)
        json_published = True
        markdown_temporary.replace(markdown_path)
        temporary_paths.remove(markdown_temporary)
    except BaseException:
        if json_published:
            if json_backup is None:
                json_path.unlink(missing_ok=True)
            else:
                json_backup.replace(json_path)
                temporary_paths.remove(json_backup)
        raise
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)


def _validate_report_date(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("report_date must be an ISO YYYY-MM-DD date")
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("report_date must be an ISO YYYY-MM-DD date") from error
    if parsed_date.isoformat() != value:
        raise ValueError("report_date must be an ISO YYYY-MM-DD date")
    return value


def _report_paths(history_dir: Path, report_date: str) -> tuple[Path, Path]:
    json_path = history_dir / f"{report_date}.json"
    markdown_path = history_dir / f"{report_date}.md"
    if json_path.parent != history_dir or markdown_path.parent != history_dir:
        raise ValueError("report paths must be direct children of history_dir")
    return json_path, markdown_path


def _read_streaks(path: Path) -> dict[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
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
        streaks[full_name] = max(streaks.get(full_name, 0), streak_days)
    return streaks


def _stage_existing_file(path: Path) -> Path | None:
    try:
        return _stage_bytes(path, path.read_bytes())
    except FileNotFoundError:
        return None


def _stage_text(path: Path, content: str) -> Path:
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _stage_bytes(path: Path, content: bytes) -> Path:
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
