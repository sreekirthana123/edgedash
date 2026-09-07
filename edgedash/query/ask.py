"""Two-call route, execute, and phrase pipeline for data questions."""

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

from edgedash import llm, storage
from edgedash.config import Config
from edgedash.query.tools import TOOLS


@dataclass(frozen=True)
class Answer:
    """Answer text and the rows that produced it."""

    text: str
    rows: list[dict]
    tool_used: str | None
    params: dict[str, Any]


MAX_QUESTION_LENGTH = 300
SESSION_WINDOW_SECONDS = 10 * 60
SESSION_QUESTION_LIMIT = 10
SUSPICIOUS_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now", re.I),
)


def _cannot_answer() -> str:
    return (
        "That question cannot be answered by the available data tools. "
        "You can ask:\n" + _available_tools_text()
    )


def _clean_question(question: Any) -> str:
    if not isinstance(question, str):
        return ""
    return "".join(
        character
        for character in question
        if unicodedata.category(character) != "Cc"
    ).strip()


def _rejection(
    question: str,
    config: Config,
    started: float,
    reason: str,
    text: str,
) -> Answer:
    storage.log_query(
        config.db_path,
        question,
        None,
        json.dumps({}, sort_keys=True),
        False,
        time.perf_counter() - started,
        reason,
    )
    return Answer(text=text, rows=[], tool_used=None, params={})


def _session_wait_seconds(session_timestamps: list[float], now: float) -> int:
    recent = [timestamp for timestamp in session_timestamps if now - timestamp < SESSION_WINDOW_SECONDS]
    session_timestamps[:] = recent
    if len(recent) < SESSION_QUESTION_LIMIT:
        return 0
    return max(1, int(SESSION_WINDOW_SECONDS - (now - min(recent)) + 0.999))


def _routing_prompt(question: str) -> str:
    """Build the model-facing routing prompt from the fixed tool registry."""
    tool_lines = []
    for name, metadata in TOOLS.items():
        tool_lines.append(
            f"- {name}: {metadata['description']}\n"
            f"  Parameters: {json.dumps(metadata['parameters'], sort_keys=True)}"
        )
    return (
        f"QUESTION:\n{question}\n\n"
        "AVAILABLE TOOLS:\n"
        + "\n".join(tool_lines)
        + "\n\nReturn exactly one JSON object with exactly these three keys: "
        '"tool", "params", and "confidence". '
        '"tool" must be one exact listed tool name or null. '
        '"params" must be a JSON object. '
        '"confidence" must be exactly "high" or "low". '
        "Choose exactly one tool only when it directly matches the question. "
        "If no tool directly matches, set tool to null. Do not pick the "
        "closest tool and do not guess. Return JSON only, with no markdown "
        "fences and no extra keys."
    )


def _available_tools_text() -> str:
    return "\n".join(
        f"- {metadata['name']}: {metadata['description']}"
        for metadata in TOOLS.values()
    )


def _phrase_prompt(question: str, rows: list[dict], summary: str) -> str:
    return (
        "QUESTION:\n"
        f"{question}\n\n"
        "ROWS:\n"
        f"{json.dumps(rows, sort_keys=True, default=str)}\n\n"
        "SUMMARY:\n"
        f"{summary}\n\n"
        "Return exactly one valid JSON object with exactly one key: \"text\". "
        "The value of \"text\" must be 2-3 sentences using only the numbers "
        "present in these rows. "
        "Do not estimate or add outside context. If the rows are empty, say "
        "the data does not contain an answer. Return JSON only, with no "
        "markdown fences and no extra keys."
    )


def _validate_route(route: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(route, dict):
        raise ValueError("Route response must be an object")
    confidence = route.get("confidence")
    if confidence not in {"high", "low"}:
        raise ValueError("Route confidence must be 'high' or 'low'")
    tool_name = route.get("tool")
    params = route.get("params", {})
    if tool_name is not None and tool_name not in TOOLS:
        raise ValueError(f"Unknown query tool: {tool_name}")
    if not isinstance(params, dict):
        raise ValueError("Query tool params must be an object")
    if tool_name is not None:
        allowed = TOOLS[tool_name]["parameters"].get("properties", {})
        unexpected = set(params) - set(allowed)
        if unexpected:
            raise ValueError(f"Unexpected params for {tool_name}: {sorted(unexpected)}")
    return tool_name, params


def _clamp_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Clamp numeric parameters from an untrusted route response."""
    clamped = dict(params)
    properties = TOOLS[tool_name]["parameters"].get("properties", {})
    for name, spec in properties.items():
        if name not in clamped or spec.get("type") != "integer":
            continue
        try:
            value = int(clamped[name])
        except (TypeError, ValueError):
            value = spec.get("default", spec["minimum"])
        clamped[name] = max(spec["minimum"], min(value, spec["maximum"]))
    return clamped


def ask(
    question: str,
    session_timestamps: list[float] | None = None,
) -> Answer:
    """Route one question, execute its fixed tool, and phrase its rows."""
    started = time.perf_counter()
    config = Config.load()
    storage.init_db(config.db_path)
    now = time.time()
    session_timestamps = session_timestamps if session_timestamps is not None else []
    wait_seconds = _session_wait_seconds(session_timestamps, now)
    if wait_seconds:
        wait_minutes = max(1, (wait_seconds + 59) // 60)
        return _rejection(
            question,
            config,
            started,
            "rejected: session rate limit",
            f"You have reached the question limit. Please try again in about {wait_minutes} minute(s).",
        )
    if storage.count_queries_today(config.db_path) >= config.daily_query_cap:
        return _rejection(
            question,
            config,
            started,
            "rejected: daily cap",
            "The data question limit for today has been reached. The dashboard remains available.",
        )

    cleaned_question = _clean_question(question)
    if not cleaned_question:
        return _rejection(
            question if isinstance(question, str) else "",
            config,
            started,
            "rejected: empty input",
            "Please enter a question about your EdgeDash data.",
        )
    if len(cleaned_question) > MAX_QUESTION_LENGTH:
        return _rejection(
            cleaned_question,
            config,
            started,
            "rejected: question too long",
            "Please keep your question to 300 characters or fewer.",
        )
    if any(pattern.search(cleaned_question) for pattern in SUSPICIOUS_PATTERNS):
        return _rejection(
            cleaned_question,
            config,
            started,
            "rejected: suspicious input",
            _cannot_answer(),
        )
    session_timestamps.append(now)
    try:
        route = llm.complete_json(
            _routing_prompt(question),
            {"tool": "string|null", "params": "object", "confidence": "string"},
            config,
        )
        tool_name, params = _validate_route(route)
    except Exception as error:
        storage.log_query(
            config.db_path,
            question,
            None,
            json.dumps({}, sort_keys=True),
            False,
            time.perf_counter() - started,
            f"query failed: {type(error).__name__}: {error}",
        )
        raise

    if tool_name is None:
        answer = Answer(
            text=_cannot_answer(),
            rows=[],
            tool_used=None,
            params={},
        )
        storage.log_query(
            config.db_path,
            question,
            None,
            json.dumps({}, sort_keys=True),
            False,
            time.perf_counter() - started,
        )
        return answer

    params = _clamp_params(tool_name, params)
    tool_function = TOOLS[tool_name]["function"]
    result = tool_function(**params, db_path=config.db_path)
    rows = result["rows"]
    summary = result["summary"]
    try:
        phrase = llm.complete_json(
            _phrase_prompt(question, rows, summary),
            {"text": "string"},
            config,
        )
    except Exception as error:
        storage.log_query(
            config.db_path,
            question,
            tool_name,
            json.dumps(params, sort_keys=True),
            False,
            time.perf_counter() - started,
            f"query failed: {type(error).__name__}: {error}",
        )
        raise
    if set(phrase) != {"text"}:
        raise ValueError('Phrasing response must contain exactly the "text" key')
    answer = Answer(
        text=phrase["text"],
        rows=rows,
        tool_used=tool_name,
        params=params,
    )
    storage.log_query(
        config.db_path,
        question,
        tool_name,
        json.dumps(params, sort_keys=True),
        True,
        time.perf_counter() - started,
    )
    return answer