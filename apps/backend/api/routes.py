import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from apps.backend.agents.core_agent import CoreAgent
from apps.backend.agents.fetch_agent import FetchAgent
from apps.backend.agents.jira_agent import JiraAgent
from apps.backend.agents.spec_agent import SpecAgent
from apps.backend.agents.tp_agent import TpAgent
from apps.backend.core.config import settings
from apps.backend.core.models import AnalyzeRequest, AnalyzeResponse, Evidence
from apps.backend.graph.build_graph import build
from apps.backend.graph.nodes import make_nodes
from apps.backend.services.cache import TTLCache
from apps.backend.services.log_fetcher import LogFetcher
from apps.backend.services.log_parser import LogParser
from apps.backend.services.run_manager import RunManager
from apps.backend.tools.dify_client import DifyClient
from apps.backend.tools.zeus_portal import ZeusPortalClient

logger = logging.getLogger(__name__)
router = APIRouter()
cache = TTLCache(settings.cache_ttl_seconds)
run_manager = RunManager()

EventCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]


def _cache_key(req: AnalyzeRequest) -> str:
    return f"{req.user_query}:{req.sku}:{req.matrix_id}:{req.test_id}:{req.zeus_test_url}"


async def _analyze_impl(
    req: AnalyzeRequest,
    *,
    use_cache: bool = True,
    run_id: Optional[str] = None,
    event_callback: Optional[EventCallback] = None,
) -> AnalyzeResponse:
    key = _cache_key(req)
    if use_cache and event_callback is None:
        cached = cache.get(key)
        if cached:
            return cached

    # services
    zeus = ZeusPortalClient()
    fetch_agent = FetchAgent(LogFetcher(zeus))
    parser = LogParser()

    # dify agents
    spec_client = DifyClient(settings.dify_spec_app_key)
    tp_client = DifyClient(settings.dify_tp_app_key)
    jira_client = DifyClient(settings.dify_jira_app_key)

    spec_agent = SpecAgent(spec_client)
    tp_agent = TpAgent(tp_client)
    jira_agent = JiraAgent(jira_client)
    core_agent = CoreAgent()

    node_fetch, node_parse, node_core_plan, node_experts, node_finalize = make_nodes(
        fetch_agent, parser, core_agent, spec_agent, tp_agent, jira_agent
    )
    graph = build(node_fetch, node_parse, node_core_plan, node_experts, node_finalize)

    init = {
        "run_id": run_id,
        "event_callback": event_callback,
        "request_id": req.request_id,
        "user_query": req.user_query,
        "sku": req.sku,
        "matrix_id": req.matrix_id,
        "test_id": req.test_id,
        "zeus_test_url": req.zeus_test_url,
    }

    out = await graph.ainvoke(init)

    tool_results = out.get("tool_results", [])
    evidences = []
    for tr in tool_results:
        evidences.extend(tr.evidences[:2])

    summary_text = (out.get("final_summary") or out.get("draft_summary") or "").strip() or "（无总结）"

    resp = AnalyzeResponse(
        request_id=req.request_id,
        overall_summary=summary_text,
        suspected_root_causes=_guess_root_causes(summary_text),
        key_evidences=evidences[:8] if evidences else [Evidence(source="none", snippet="无证据（可能 Zeus/Dify 未配置）", meta={})],
        tool_results=tool_results,
        recommendations=_guess_reco(summary_text),
        next_actions=_default_next_actions(),
        raw=out,
    )

    if use_cache and event_callback is None:
        cache.set(key, resp)
    return resp


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    return await _analyze_impl(req, use_cache=True)


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


def _guess_root_causes(text: str):
    # MVP：简单 fallback
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    cands = [l for l in lines if ("根因" in l or "原因" in l)]
    return cands[:3] if cands else ["信息不足：需要更多日志/寄存器快照来定位RDY=0原因"]


def _guess_reco(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    cands = [l for l in lines if ("建议" in l or "下一步" in l)]
    return cands[:6] if cands else ["补充采集：CSTS/CC/APST配置与时序", "对比不同FW/平台复现概率"]


def _default_next_actions():
    return [
        "确认 FW 版本、平台、PCIe 拓扑、电源控制方式",
        "复现时抓取更完整 log 与寄存器快照（CSTS/CC 等）",
        "若涉及低功耗/APST：记录 Set Features(APST) 参数与 PS 切换时序",
    ]
