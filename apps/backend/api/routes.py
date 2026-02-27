import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from apps.backend.core.config import settings
from apps.backend.core.errors import JupiterError
from apps.backend.core.models import AnalyzeRequest, AnalyzeResponse
from apps.backend.services.cache import TTLCache
from apps.backend.services.run_manager import RunManager
from jupiter_core.workflow import run_analysis

logger = logging.getLogger(__name__)
router = APIRouter()
cache = TTLCache(settings.cache_ttl_seconds)
run_manager = RunManager()

EventCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]


async def _analyze_impl(
    req: AnalyzeRequest,
    *,
    use_cache: bool = True,
    run_id: Optional[str] = None,
    event_callback: Optional[EventCallback] = None,
) -> AnalyzeResponse:
    return await run_analysis(
        req,
        use_cache=use_cache,
        run_id=run_id,
        event_callback=event_callback,
        cache=cache,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return await _analyze_impl(req, use_cache=True)
    except JupiterError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/runs")
async def create_run(req: AnalyzeRequest) -> Dict[str, Any]:
    run_id = await run_manager.create_run(req.model_dump())

    async def _emit(evt: Dict[str, Any]) -> None:
        await run_manager.append_event(run_id, evt)

    async def _runner() -> None:
        await run_manager.set_status(run_id, "running")
        await run_manager.append_event(run_id, {"type": "run.started", "payload": {"run_id": run_id}})
        try:
            resp = await _analyze_impl(
                req,
                use_cache=False,
                run_id=run_id,
                event_callback=_emit,
            )
            await run_manager.finish(run_id, resp.model_dump(mode="json"))
        except Exception as e:
            logger.exception("run %s failed", run_id)
            await run_manager.fail(run_id, str(e))

    asyncio.create_task(_runner())
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Dict[str, Any]:
    run = await run_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    run = await run_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator():
        current = after_seq
        while True:
            events = await run_manager.list_events(run_id, after_seq=current)
            for evt in events:
                current = int(evt.get("seq", current))
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            latest = await run_manager.get_run(run_id)
            if latest is None:
                break
            if latest.get("done") and not events:
                yield f"data: {json.dumps({'type': 'stream.closed', 'run_id': run_id}, ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
