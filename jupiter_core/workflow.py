from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from apps.backend.agents.core_agent import CoreAgent
from apps.backend.agents.evidence_judge import EvidenceJudge
from apps.backend.agents.fetch_agent import FetchAgent
from apps.backend.agents.intent_parser_agent import IntentParserAgent
from apps.backend.agents.jira_agent import JiraAgent
from apps.backend.agents.spec_agent import SpecAgent
from apps.backend.agents.tp_agent import TpAgent
from apps.backend.core.config import settings
from apps.backend.core.models import AnalyzeRequest, AnalyzeResponse, Evidence
from apps.backend.graph.build_graph import build
from apps.backend.graph.nodes import make_nodes
from apps.backend.services.cache import TTLCache
from apps.backend.services.input_validator import InputValidator
from apps.backend.services.log_fetcher import LogFetcher
from apps.backend.services.log_parser import LogParser
from apps.backend.tools.dify_client import DifyClient
from apps.backend.tools.zeus_portal import ZeusPortalClient

EventCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]


def _cache_key(req: AnalyzeRequest) -> str:
    return f"{req.user_query}:{req.sku}:{req.matrix_id}:{req.test_id}:{req.zeus_test_url}"


def _guess_root_causes(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cands = [line for line in lines if ("根因" in line or "原因" in line)]
    return cands[:3] if cands else ["信息不足：需要更多日志/寄存器快照来定位RDY=0原因"]


def _guess_reco(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cands = [line for line in lines if ("建议" in line or "下一步" in line)]
    return cands[:6] if cands else ["补充采集：CSTS/CC/APST配置与时序", "对比不同FW/平台复现概率"]


def _default_next_actions() -> list[str]:
    return [
        "确认 FW 版本、平台、PCIe 拓扑、电源控制方式",
        "复现时抓取更完整 log 与寄存器快照（CSTS/CC 等）",
        "若涉及低功耗/APST：记录 Set Features(APST) 参数与 PS 切换时序",
    ]


def _sanitize_for_response(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _sanitize_for_response(v)
            for k, v in value.items()
            if not callable(v)
        }
    if isinstance(value, list):
        return [_sanitize_for_response(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_for_response(v) for v in value]
    if callable(value):
        return None
    return value


async def run_analysis(
    req: AnalyzeRequest,
    *,
    use_cache: bool = True,
    run_id: Optional[str] = None,
    event_callback: Optional[EventCallback] = None,
    cache: Optional[TTLCache] = None,
) -> AnalyzeResponse:
    """
    Shared workflow runner for both FastAPI and Streamlit entrypoints.
    """
    key = _cache_key(req)
    if use_cache and cache is not None and event_callback is None:
        cached = cache.get(key)
        if cached:
            return cached

    zeus = ZeusPortalClient()
    fetch_agent = FetchAgent(LogFetcher(zeus))
    intent_parser = IntentParserAgent()
    validator = InputValidator()
    parser = LogParser()

    spec_client = DifyClient(settings.dify_spec_app_key)
    tp_client = DifyClient(settings.dify_tp_app_key)
    jira_client = DifyClient(settings.dify_jira_app_key)

    spec_agent = SpecAgent(spec_client)
    tp_agent = TpAgent(tp_client)
    jira_agent = JiraAgent(jira_client)
    core_agent = CoreAgent()
    evidence_judge = EvidenceJudge()

    (
        node_intent,
        node_validate,
        node_fetch,
        node_parse,
        node_core_plan,
        node_experts,
        node_evidence_judge,
        node_retry_plan,
        node_finalize,
    ) = make_nodes(
        fetch_agent, intent_parser, validator, parser, core_agent, evidence_judge, spec_agent, tp_agent, jira_agent
    )
    graph = build(
        node_intent,
        node_validate,
        node_fetch,
        node_parse,
        node_core_plan,
        node_experts,
        node_evidence_judge,
        node_retry_plan,
        node_finalize,
    )

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

    sanitized_raw = _sanitize_for_response(out)

    resp = AnalyzeResponse(
        request_id=req.request_id,
        overall_summary=summary_text,
        suspected_root_causes=_guess_root_causes(summary_text),
        key_evidences=evidences[:8] if evidences else [Evidence(source="none", snippet="无证据（可能 Zeus/Dify 未配置）", meta={})],
        tool_results=tool_results,
        recommendations=_guess_reco(summary_text),
        next_actions=_default_next_actions(),
        raw=sanitized_raw,
    )

    if use_cache and cache is not None and event_callback is None:
        cache.set(key, resp)
    return resp
