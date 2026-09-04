from __future__ import annotations

import inspect

from scout_email.llm.prompts import build_system_prompt
from scout_email.strategy.service import StrategyService


def test_strategist_prompt_does_not_invent_sales_qualification_prerequisites():
    prompt = build_system_prompt(task="strategist", prompt_version="strategist:v2")

    assert "exact decision-maker identity is not required" in prompt
    assert "incumbent vendor or active web-development contract" in prompt
    assert "proof that the prospect is actively buying or currently in-market" in prompt
    assert "must not by themselves justify RESEARCH_MORE" in prompt


def test_strategy_service_uses_v2_prompt_by_default():
    default = inspect.signature(StrategyService.__init__).parameters["prompt_version"].default

    assert default == "strategist:v2"
