"""Configuration loading and default search rules."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

DEFAULT_RULES: list[dict[str, Any]] = [
    {"type": "include", "keyword": "AI Engineer", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "AI/ML Engineer", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "Machine Learning", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "ML Engineer", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "Deep Learning", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "LLM", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "MLOps", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "NLP", "weight": 4, "enabled": True},
    {"type": "include", "keyword": "Computer Vision", "weight": 4, "enabled": True},
    {"type": "include", "keyword": "Data Scientist", "weight": 4, "enabled": True},
    {"type": "include", "keyword": "머신러닝", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "딥러닝", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "생성형 AI", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "AI", "weight": 3, "enabled": True},
    {"type": "include", "keyword": "신입", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "Junior", "weight": 4, "enabled": True},
    {"type": "include", "keyword": "Entry", "weight": 4, "enabled": True},
    {"type": "include", "keyword": "경력무관", "weight": 5, "enabled": True},
    {"type": "include", "keyword": "공채", "weight": 2, "enabled": True},
    {"type": "exclude", "keyword": "경력 3년", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "경력 5년", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "경력 7년", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "시니어", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "Senior", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "Lead", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "Principal", "weight": -10, "enabled": True},
    {"type": "exclude", "keyword": "Manager", "weight": -8, "enabled": True},
    {"type": "exclude", "keyword": "PM", "weight": -5, "enabled": True},
    {"type": "exclude", "keyword": "PO", "weight": -5, "enabled": True},
    {"type": "exclude", "keyword": "마케팅", "weight": -5, "enabled": True},
    {"type": "exclude", "keyword": "영업", "weight": -5, "enabled": True},
    {"type": "exclude", "keyword": "상품기획", "weight": -5, "enabled": True},
    {"type": "exclude", "keyword": "교육", "weight": -5, "enabled": True},
    {"type": "exclude", "keyword": "RA", "weight": -5, "enabled": True},
]


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load YAML and validate the small amount of structure the runner needs."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency install issue
        raise RuntimeError("PyYAML is required; install requirements.txt") from exc
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a YAML mapping")
    result = copy.deepcopy(data)
    result.setdefault("timezone", "Asia/Seoul")
    result.setdefault("filter", {})
    result.setdefault("sources", {})
    result.setdefault("notifications", {})
    result["filter"].setdefault("strict_entry_level", False)
    result["filter"].setdefault("min_score", 6)
    result["filter"].setdefault("rules", copy.deepcopy(DEFAULT_RULES))
    return result


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        # Environment variables are already supplied by GitHub Actions or the shell.
        return


def enabled(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", "n", ""}
    return bool(value)
