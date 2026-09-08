from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class Config:
    target_role: str
    target_city: str
    keywords: list[str]
    my_skills: list[str]
    experience_years: int
    db_path: str
    min_fit_score: int
    sources: list[str]
    use_mock_fetcher: bool
    llm_provider: str
    llm_model: str
    target_seniority: str
    score_weights: dict[str, float]
    score_batch_size: int
    skill_aliases: dict[str, str]
    min_spread: float
    min_stdev: float
    max_empty_extraction_pct: float
    max_skills_per_listing: int
    min_gap_sample: int
    max_data_age_days: int
    daily_query_cap: int
    extraction_retry_hours: float = 24.0

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "Config":
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"config.yaml not found at {path.absolute()}. "
                "Create it using config.yaml as a template."
            )

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        defaults = {
            "target_role": "Data Analyst",
            "target_city": "Bengaluru",
            "keywords": ["python", "sql", "analytics"],
            "my_skills": ["python", "sql", "tableau"],
            "experience_years": 3,
            "db_path": "edgedash.db",
            "min_fit_score": 70,
            "sources": ["arbeitnow"],
            "use_mock_fetcher": False,
            "llm_provider": "gemini",
            "llm_model": "gemini-3.6-flash",
            "target_seniority": "mid",
            "score_weights": {
                "skills_match": 0.35,
                "seniority_match": 0.25,
                "location_match": 0.20,
                "recency": 0.20,
            },
            "score_batch_size": 25,
            "skill_aliases": {},
            "min_spread": 20.0,
            "min_stdev": 5.0,
            "max_empty_extraction_pct": 0.20,
            "max_skills_per_listing": 30,
            "min_gap_sample": 3,
            "max_data_age_days": 7,
            "daily_query_cap": 200,
            "extraction_retry_hours": 24.0,
        }

        for key, default_value in defaults.items():
            if key not in data:
                data[key] = default_value

        return cls(
            target_role=data["target_role"],
            target_city=data["target_city"],
            keywords=data["keywords"],
            my_skills=data["my_skills"],
            experience_years=data["experience_years"],
            db_path=data["db_path"],
            min_fit_score=data["min_fit_score"],
            sources=data["sources"],
            use_mock_fetcher=data["use_mock_fetcher"],
            llm_provider=data["llm_provider"],
            llm_model=data["llm_model"],
            target_seniority=data["target_seniority"],
            score_weights=data["score_weights"],
            score_batch_size=data["score_batch_size"],
            skill_aliases=data["skill_aliases"],
            min_spread=data["min_spread"],
            min_stdev=data["min_stdev"],
            max_empty_extraction_pct=data["max_empty_extraction_pct"],
            max_skills_per_listing=data["max_skills_per_listing"],
            min_gap_sample=data["min_gap_sample"],
            max_data_age_days=data["max_data_age_days"],
            daily_query_cap=data["daily_query_cap"],
            extraction_retry_hours=data["extraction_retry_hours"],
        )
