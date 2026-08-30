from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from scout_email.llm.context import sanitize_context


def build_system_prompt(*, task: str, prompt_version: str, repair: bool = False) -> str:
    if not task.strip():
        raise ValueError("task is required")
    if not prompt_version.strip():
        raise ValueError("prompt_version is required")

    base = (
        f"Task: {task}. Prompt version: {prompt_version}. "
        "Return only JSON that validates against the supplied schema. "
        "Do not add markdown fences, commentary, or fields outside the schema."
    )
    if repair:
        return (
            "Schema repair attempt. "
            + base
            + " Correct the previous invalid output using the validation feedback; do not change task intent."
        )
    return base


def build_user_prompt(context: Mapping[str, Any]) -> str:
    cleaned = sanitize_context(context)
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_repair_user_prompt(
    *,
    context: Mapping[str, Any],
    invalid_output: str,
    validation_error: str,
) -> str:
    payload = {
        "context": sanitize_context(context),
        "previous_invalid_output": invalid_output[:12_000],
        "validation_feedback": validation_error[:4_000],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
