import pytest

from scout_email.strategy.jobs import run_strategy_job


class FakeStrategyService:
    def __init__(self) -> None:
        self.lead_ids: list[int] = []

    async def strategize(self, *, lead_id: int):
        self.lead_ids.append(lead_id)
        return {"decision": "SKIP"}


@pytest.mark.asyncio
async def test_run_strategy_job_delegates_one_persisted_lead():
    service = FakeStrategyService()

    result = await run_strategy_job(service, lead_id=42)

    assert result == {"decision": "SKIP"}
    assert service.lead_ids == [42]
