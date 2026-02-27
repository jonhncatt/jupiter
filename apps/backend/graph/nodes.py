import asyncio
import inspect
import time
from apps.backend.core.errors import InputValidationError
from apps.backend.graph.state import GraphState
from apps.backend.services.log_parser import LogParser
from apps.backend.services.input_validator import InputValidator
from apps.backend.agents.fetch_agent import FetchAgent
from apps.backend.agents.intent_parser_agent import IntentParserAgent
from apps.backend.agents.core_agent import CoreAgent
from apps.backend.agents.spec_agent import SpecAgent
from apps.backend.agents.tp_agent import TpAgent
from apps.backend.agents.jira_agent import JiraAgent
from apps.backend.core.models import ToolResult


def _append_trace(state: GraphState, entry: dict) -> list[dict]:
    trace = list(state.get("debug_trace", []))
    trace.append(entry)
    return trace


async def _emit_event(state: GraphState, event_type: str, payload: dict) -> None:
    callback = state.get("event_callback")
    if not callback:
        return
    evt = {"type": event_type, "payload": payload}
    try:
        out = callback(evt)
        if inspect.isawaitable(out):
            await out
    except Exception:
        # debug callback must never break main workflow
        return


def make_nodes(
    fetch_agent: FetchAgent,
    intent_parser: IntentParserAgent,
    validator: InputValidator,
    parser: LogParser,
    core: CoreAgent,
    spec: SpecAgent,
    tp: TpAgent,
    jira: JiraAgent,
):
    async def node_intent(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "intent", "run_id": state.get("run_id"), "status": "started"},
        )
        intent = await intent_parser.run(
            user_query=state.get("user_query", ""),
            sku=state.get("sku"),
            matrix_id=state.get("matrix_id"),
            test_id=state.get("test_id"),
            zeus_test_url=state.get("zeus_test_url"),
        )
        trace = _append_trace(
            state,
            {
                "node": "intent",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "source": intent.get("source"),
                "sku": intent.get("sku"),
                "matrix_id": intent.get("matrix_id"),
                "test_id": intent.get("test_id"),
                "zeus_test_url": intent.get("zeus_test_url"),
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "intent",
                "run_id": state.get("run_id"),
                "status": "ok",
                "duration_ms": trace[-1]["duration_ms"],
                "source": trace[-1]["source"],
                "sku": trace[-1]["sku"],
                "matrix_id": trace[-1]["matrix_id"],
                "test_id": trace[-1]["test_id"],
                "zeus_test_url": trace[-1]["zeus_test_url"],
            },
        )
        return {**state, "intent": intent, "debug_trace": trace}

    async def node_validate(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "validate", "run_id": state.get("run_id"), "status": "started"},
        )
        validation = validator.validate(
            state.get("intent", {}),
            {
                "sku": state.get("sku"),
                "matrix_id": state.get("matrix_id"),
                "test_id": state.get("test_id"),
                "zeus_test_url": state.get("zeus_test_url"),
                "user_query": state.get("user_query"),
            },
        )
        resolved = validation.get("resolved", {})
        trace = _append_trace(
            state,
            {
                "node": "validate",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "valid": validation.get("valid"),
                "errors": validation.get("errors", []),
                "warnings": validation.get("warnings", []),
                "resolved": resolved,
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "validate",
                "run_id": state.get("run_id"),
                "status": "ok" if validation.get("valid") else "warn",
                "duration_ms": trace[-1]["duration_ms"],
                "valid": validation.get("valid"),
                "errors": validation.get("errors", []),
                "warnings": validation.get("warnings", []),
                "resolved": resolved,
            },
        )
        if not validation.get("valid"):
            msg = (
                "Input validation failed: "
                + ", ".join(validation.get("errors", []))
                + (f" | warnings: {', '.join(validation.get('warnings', []))}" if validation.get("warnings") else "")
            )
            await _emit_event(
                state,
                "node.failed",
                {
                    "node": "validate",
                    "run_id": state.get("run_id"),
                    "status": "error",
                    "error": msg[:500],
                },
            )
            raise InputValidationError(msg)
        return {
            **state,
            "validation": validation,
            "sku": resolved.get("sku", state.get("sku")),
            "matrix_id": resolved.get("matrix_id", state.get("matrix_id")),
            "test_id": resolved.get("test_id", state.get("test_id")),
            "zeus_test_url": resolved.get("zeus_test_url", state.get("zeus_test_url")),
            "user_query": resolved.get("user_query", state.get("user_query")),
            "debug_trace": trace,
        }

    async def node_fetch(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "fetch", "run_id": state.get("run_id"), "status": "started"},
        )
        try:
            fetched = await fetch_agent.run(
                sku=state.get("sku"),
                matrix_id=state.get("matrix_id"),
                test_id=state.get("test_id"),
                zeus_test_url=state.get("zeus_test_url"),
            )
        except Exception as e:
            await _emit_event(
                state,
                "node.failed",
                {
                    "node": "fetch",
                    "run_id": state.get("run_id"),
                    "status": "error",
                    "error": str(e)[:500],
                },
            )
            raise
        trace = _append_trace(
            state,
            {
                "node": "fetch",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "fetch_meta": fetched.get("fetch_meta", {}),
                "raw_log_chars": len(fetched.get("raw_log", "")),
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "fetch",
                "run_id": state.get("run_id"),
                "status": "ok" if fetched.get("fetch_meta", {}).get("reason") == "ok" else "warn",
                "duration_ms": trace[-1]["duration_ms"],
                "raw_log_chars": trace[-1]["raw_log_chars"],
                "source": fetched.get("fetch_meta", {}).get("source", "-"),
                "reason": fetched.get("fetch_meta", {}).get("reason", ""),
                "files_count": fetched.get("fetch_meta", {}).get("files_count", 0),
                "test_url": fetched.get("fetch_meta", {}).get("test_url"),
                "zip_url": fetched.get("fetch_meta", {}).get("zip_url"),
                "downloaded_zip_path": fetched.get("fetch_meta", {}).get("downloaded_zip_path"),
                "status_code": fetched.get("fetch_meta", {}).get("status_code"),
                "final_url": fetched.get("fetch_meta", {}).get("final_url"),
                "extract_status": fetched.get("fetch_meta", {}).get("extract_status"),
                "top_files": fetched.get("fetch_meta", {}).get("top_files", []),
                "selected_text_files": fetched.get("fetch_meta", {}).get("selected_text_files", []),
                "zip_member_count": fetched.get("fetch_meta", {}).get("zip_member_count", 0),
            },
        )
        return {**state, **fetched, "debug_trace": trace}

    async def node_parse(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "parse", "run_id": state.get("run_id"), "status": "started"},
        )
        p = parser.parse(state["raw_log"])
        parsed = {
            "errors": p.errors,
            "warnings": p.warnings,
            "highlights": p.highlights,
            "tokens": p.tokens,
            "domain_context": p.domain_context,
        }
        trace = _append_trace(
            state,
            {
                "node": "parse",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "errors": len(parsed["errors"]),
                "warnings": len(parsed["warnings"]),
                "highlights": len(parsed["highlights"]),
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "parse",
                "run_id": state.get("run_id"),
                "status": "ok",
                "duration_ms": trace[-1]["duration_ms"],
                "errors": trace[-1]["errors"],
                "warnings": trace[-1]["warnings"],
                "highlights": trace[-1]["highlights"],
                "tokens": parsed.get("tokens", {}),
                "sample_errors": parsed.get("errors", [])[:3],
                "domain_context": parsed.get("domain_context", {}),
            },
        )
        return {**state, "parsed": parsed, "debug_trace": trace}

    async def node_core_plan(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "core_plan", "run_id": state.get("run_id"), "status": "started"},
        )
        plan = await core.plan(
            state["user_query"],
            state["parsed"],
            raw_log=state.get("raw_log", ""),
        )
        trace = _append_trace(
            state,
            {
                "node": "core_plan",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "planner_source": plan.get("planner_source", "unknown"),
                "selected_tools": plan.get("selected_tools", []),
                "reason": plan.get("reason", ""),
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "core_plan",
                "run_id": state.get("run_id"),
                "status": "ok",
                "duration_ms": trace[-1]["duration_ms"],
                "planner_source": trace[-1]["planner_source"],
                "selected_tools": trace[-1]["selected_tools"],
                "reason": trace[-1]["reason"],
            },
        )
        return {**state, "core_plan": plan, "debug_trace": trace}

    async def node_experts(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "experts", "run_id": state.get("run_id"), "status": "started"},
        )
        plan = state.get("core_plan", {})
        selected = plan.get("selected_tools", []) or []
        expert_queries = plan.get("expert_queries", {}) or {}

        ctx = {
            "tokens": state["parsed"]["tokens"],
            "highlights": state["parsed"]["highlights"],
            "domain_context": state["parsed"].get("domain_context", {}),
            "round_hint": plan.get("round_hint", 1),
            "event_callback": state.get("event_callback"),
            "run_id": state.get("run_id"),
        }

        tasks = []
        task_names = []

        if "spec" in selected:
            spec_query = expert_queries.get("spec") or state["user_query"]
            await _emit_event(
                state,
                "agent.started",
                {
                    "agent": "spec_agent(dify)",
                    "run_id": state.get("run_id"),
                    "query_preview": spec_query[:300],
                },
            )
            tasks.append(spec.run(spec_query, ctx))
            task_names.append("spec")
        if "tp" in selected:
            tp_query = expert_queries.get("tp") or state["user_query"]
            await _emit_event(
                state,
                "agent.started",
                {
                    "agent": "tp_agent(dify)",
                    "run_id": state.get("run_id"),
                    "query_preview": tp_query[:300],
                },
            )
            tasks.append(tp.run(tp_query, ctx))
            task_names.append("tp")
        if "jira" in selected:
            jira_query = expert_queries.get("jira") or state["user_query"]
            await _emit_event(
                state,
                "agent.started",
                {
                    "agent": "jira_agent(dify)",
                    "run_id": state.get("run_id"),
                    "query_preview": jira_query[:300],
                },
            )
            tasks.append(jira.run(jira_query, ctx))
            task_names.append("jira")

        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

        tool_results = []
        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                tool_results.append(ToolResult(tool=f"{name}_agent", ok=False, summary=str(result), evidences=[]))
                await _emit_event(
                    state,
                    "agent.finished",
                    {
                        "agent": f"{name}_agent",
                        "run_id": state.get("run_id"),
                        "ok": False,
                        "summary": str(result)[:500],
                    },
                )
            else:
                tool_results.append(result)
                await _emit_event(
                    state,
                    "agent.finished",
                    {
                        "agent": result.tool,
                        "run_id": state.get("run_id"),
                        "ok": result.ok,
                        "summary": result.summary[:500],
                    },
                )

        if not selected:
            tool_results.append(
                ToolResult(
                    tool=core.name,
                    ok=True,
                    summary="Core agent决定无需调用下属专家，直接做最终结论。",
                    evidences=[],
                    debug={"status": "skipped_all_experts"},
                )
            )

        trace = _append_trace(
            state,
            {
                "node": "experts",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "selected_tools": selected,
                "expert_queries": expert_queries,
                "results": [{"tool": r.tool, "ok": r.ok, "summary": r.summary} for r in tool_results],
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "experts",
                "run_id": state.get("run_id"),
                "status": "ok" if all(r.ok for r in tool_results) else "warn",
                "duration_ms": trace[-1]["duration_ms"],
                "selected_tools": trace[-1]["selected_tools"],
                "expert_queries": trace[-1]["expert_queries"],
                "results": trace[-1]["results"],
            },
        )
        return {**state, "tool_results": tool_results, "debug_trace": trace}

    async def node_finalize(state: GraphState) -> GraphState:
        t0 = time.perf_counter()
        await _emit_event(
            state,
            "node.started",
            {"node": "finalize", "run_id": state.get("run_id"), "status": "started"},
        )
        final_summary = await core.finalize(
            query=state["user_query"],
            parsed=state["parsed"],
            core_plan=state.get("core_plan", {}),
            expert_reports=state.get("tool_results", []),
        )
        # Keep draft_summary for backward compatibility with existing API fields.
        trace = _append_trace(
            state,
            {
                "node": "finalize",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "summary_chars": len(final_summary or ""),
            },
        )
        await _emit_event(
            state,
            "node.finished",
            {
                "node": "finalize",
                "run_id": state.get("run_id"),
                "status": "ok",
                "duration_ms": trace[-1]["duration_ms"],
                "summary_chars": trace[-1]["summary_chars"],
            },
        )
        return {**state, "final_summary": final_summary, "draft_summary": final_summary, "debug_trace": trace}

    return node_intent, node_validate, node_fetch, node_parse, node_core_plan, node_experts, node_finalize
