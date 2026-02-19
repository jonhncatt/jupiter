import asyncio
from apps.backend.graph.state import GraphState
from apps.backend.services.log_parser import LogParser
from apps.backend.agents.fetch_agent import FetchAgent
from apps.backend.agents.core_agent import CoreAgent
from apps.backend.agents.spec_agent import SpecAgent
from apps.backend.agents.tp_agent import TpAgent
from apps.backend.agents.jira_agent import JiraAgent
from apps.backend.core.models import ToolResult


def make_nodes(
    fetch_agent: FetchAgent,
    parser: LogParser,
    core: CoreAgent,
    spec: SpecAgent,
    tp: TpAgent,
    jira: JiraAgent,
):
    async def node_fetch(state: GraphState) -> GraphState:
        fetched = await fetch_agent.run(
            matrix_id=state.get("matrix_id"),
            test_id=state.get("test_id"),
            zeus_test_url=state.get("zeus_test_url"),
        )
        return {**state, **fetched}

    async def node_parse(state: GraphState) -> GraphState:
        p = parser.parse(state["raw_log"])
        parsed = {
            "errors": p.errors,
            "warnings": p.warnings,
            "highlights": p.highlights,
            "tokens": p.tokens,
        }
        return {**state, "parsed": parsed}

    async def node_core_plan(state: GraphState) -> GraphState:
        plan = await core.plan(
            state["user_query"],
            state["parsed"],
            raw_log=state.get("raw_log", ""),
        )
        return {**state, "core_plan": plan}

    async def node_experts(state: GraphState) -> GraphState:
        plan = state.get("core_plan", {})
        selected = plan.get("selected_tools", []) or []

        ctx = {
            "tokens": state["parsed"]["tokens"],
            "highlights": state["parsed"]["highlights"],
            "round_hint": plan.get("round_hint", 1),
        }
        q = state["user_query"]

        tasks = []
        task_names = []

        if "spec" in selected:
            tasks.append(spec.run(q, ctx))
            task_names.append("spec")
        if "tp" in selected:
            tasks.append(tp.run(q, ctx))
            task_names.append("tp")
        if "jira" in selected:
            tasks.append(jira.run(q, ctx))
            task_names.append("jira")

        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

        tool_results = []
        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                tool_results.append(ToolResult(tool=f"{name}_agent", ok=False, summary=str(result), evidences=[]))
            else:
                tool_results.append(result)

        if not selected:
            tool_results.append(
                ToolResult(
                    tool=core.name,
                    ok=True,
                    summary="Core agent决定无需调用下属专家，直接做最终结论。",
                    evidences=[],
                )
            )

        return {**state, "tool_results": tool_results}

    async def node_finalize(state: GraphState) -> GraphState:
        final_summary = await core.finalize(
            query=state["user_query"],
            parsed=state["parsed"],
            core_plan=state.get("core_plan", {}),
            expert_reports=state.get("tool_results", []),
        )
        # Keep draft_summary for backward compatibility with existing API fields.
        return {**state, "final_summary": final_summary, "draft_summary": final_summary}

    return node_fetch, node_parse, node_core_plan, node_experts, node_finalize
