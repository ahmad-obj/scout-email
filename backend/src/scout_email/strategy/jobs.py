from __future__ import annotations

from scout_email.strategy.schemas import StrategyOutput
from scout_email.strategy.service import StrategyService


async def run_strategy_job(service: StrategyService, *, lead_id: int) -> StrategyOutput:
    """Execute one evidence-bounded strategy selection job for a persisted lead."""
    return await service.strategize(lead_id=lead_id)
