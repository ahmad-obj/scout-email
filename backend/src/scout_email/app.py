from fastapi import FastAPI

from scout_email.campaigns.routes import router as campaigns_router
from scout_email.leads.routes import router as leads_router
from scout_email.logging import configure_logging

configure_logging()
app = FastAPI(title="Scout Email", version="0.1.0")
app.include_router(campaigns_router)
app.include_router(leads_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
