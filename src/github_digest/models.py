from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class TrendingRepo:
    rank: int
    full_name: str
    url: str
    description: str = ""
    language: str = "Unknown"
    stars: int = 0
    stars_today: int = field(default=0, compare=False)
    readme: str = ""
    image_url: str = field(default="", compare=False)
    streak_days: int = 1
    summary_zh: str = ""
    simple_summary_zh: str = field(default="", compare=False)
    summary_source: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DailyReport:
    report_date: str
    generated_at: str
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
    generated_at: str
    stage: str
    attempts: int
    error: str
    likely_causes: tuple[str, ...]
    actions_url: str
