from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DailyReport:
    report_date: date
    generated_at: datetime
    scope: str = "global/all-languages/daily"
    repositories: list[TrendingRepo] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "report_date": self.report_date,
            "generated_at": self.generated_at,
            "scope": self.scope,
            "repositories": [repository.to_dict() for repository in self.repositories],
        }


@dataclass(slots=True)
class FailureReport:
    generated_at: datetime
    stage: str
    attempts: int
    error: str
    likely_causes: tuple[str, ...]
    actions_url: str
