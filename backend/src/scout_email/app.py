from fastapi import FastAPI

from scout_email.approval.routes import router as approval_router
from scout_email.campaigns.routes import router as campaigns_router
from scout_email.jobs.routes import router as jobs_router
from scout_email.leads.routes import router as leads_router
from scout_email.logging import configure_logging
from scout_email.messaging.routes import router as messaging_router
from scout_email.replies.routes import router as replies_router
from scout_email.ui.routes import router as review_ui_router

configure_logging()
app = FastAPI(title="Scout Email", version="0.1.0")
app.include_router(campaigns_router)
app.include_router(leads_router)
app.include_router(jobs_router)
app.include_router(approval_router)
app.include_router(messaging_router)
app.include_router(replies_router)
app.include_router(review_ui_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
