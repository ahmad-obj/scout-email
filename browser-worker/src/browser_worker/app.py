from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from browser_worker.maps import MapsSearchError, search_maps
from browser_worker.render import BrowserNavigationError, UnsafeTargetError, render_page
from browser_worker.runtime import BrowserRuntime, BrowserUnavailableError
from browser_worker.schemas import BrowserMapLead, MapsSearchRequest, RenderRequest, RenderResponse
from browser_worker.settings import BrowserWorkerSettings

settings = BrowserWorkerSettings()
runtime = BrowserRuntime(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="Scout Email Browser Worker", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/maps/search", response_model=list[BrowserMapLead])
async def maps_search(request: MapsSearchRequest) -> list[BrowserMapLead]:
    try:
        return await search_maps(runtime, request.query, request.max_results)
    except MapsSearchError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except BrowserUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/render", response_model=RenderResponse)
async def render(request: RenderRequest) -> RenderResponse:
    try:
        return await render_page(runtime, request, settings)
    except (UnsafeTargetError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except BrowserNavigationError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except BrowserUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
