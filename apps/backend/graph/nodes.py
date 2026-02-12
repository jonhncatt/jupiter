import asyncio
import logging
from apps.backend.graph.state import GraphState
from apps.backend.services.log_fetcher import LogFetcher
from apps.backend.services.log_parser import LogParser
from apps.backend.agents.core_agent import CoreAgent
from apps.backend.agents.spec_agent import SpecAgent
from apps.backend.agents.tp_agent import TpAgent
from apps.backend.agents.jira_agent import JiraAgent
from apps.backend.core.models import ToolResult
from apps.backend.llm.openai_client import chat

logger = logging.getLogger(__name__)

SYSTEM_SUMMARY = """你是SSD测试日志分析专家。基于：
- 解析log提取结果
- Spec/TP(Dify)的证据片段
请输出结构化报告（中文）：
1) 总结（2-5句）
2) 可能根因（<=3条，按可能性排序）
3) 证据（引用关键片段）
4) 建议（可执行）
5) 下一步动作（收集哪些信息/怎么复现）
要求：避免空话；证据要贴近原文；若信息不足要明确说明缺口。"""


def make_nodes(
    fetcher: LogFetcher,
    parser: LogParser,
    core: CoreAgent,
    spec: SpecAgent,
    tp: TpAgent,
    jira: JiraAgent,
):
    async def node_fetch(state: GraphState) -> GraphState:
        raw = await fetcher.fetch_raw_log(
            matrix_id=state.get("matrix_id"),
            test_id=state.get("test_id"),
            zeus_test_url=state.get("zeus_test_url"),
        )
        return {**state, "raw_log": raw}

    async def node_parse(state: GraphState) -> GraphState:
        p = parser.parse(state["raw_log"])
        parsed = {
            "errors": p.errors,
            "warnings": p.warnings,
            "highlights": p.highlights,
            "tokens": p.tokens,
        }
        return {**state, "parsed": parsed}

    async def node_core(state: GraphState) -> GraphState:
        plan = await core.run(state["user_query"], state["parsed"])
        return {**state, "core_plan": plan}

    async def node_tools(state: GraphState) -> GraphState:
        ctx = {
            "tokens": state["parsed"]["tokens"],
            "highlights": state["parsed"]["highlights"],
        }
        q = state["user_query"]
        plan = state.get("core_plan", {})
        selected = plan.get("selected_tools", []) or []

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

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []

        tool_results = []
        for name, r in zip(task_names, results):
            if isinstance(r, Exception):
                tool_results.append(ToolResult(tool=f"{name}_agent", ok=False, summary=str(r), evidences=[]))
            else:
                tool_results.append(r)

        if not selected:
            tool_results.append(
                ToolResult(
                    tool=core.name,
                    ok=True,
                    summary="Core agent决定本次不调用RAG子agent，直接进入总结。",
                    evidences=[],
                )
            )

        return {**state, "tool_results": tool_results}

    async def node_summarize(state: GraphState) -> GraphState:
        parsed = state["parsed"]
        plan = state.get("core_plan", {})
        tool_results = state.get("tool_results", [])

        evidence_lines = []
        evidence_lines.append("【核心调度决策】")
        evidence_lines.append(
            f"- need_rag={plan.get('need_rag')} selected_tools={plan.get('selected_tools', [])} reason={plan.get('reason', '')}"
        )

        evidence_lines.append("【解析log-关键】")
        evidence_lines += parsed.get("highlights", [])[:20]

        evidence_lines.append("\n【Dify工具证据】")
        for tr in tool_results:
            evidence_lines.append(f"- {tr.tool} ok={tr.ok}: {tr.summary}")
            for ev in tr.evidences[:3]:
                evidence_lines.append(f"  * ({ev.source}) {ev.snippet}")

        user = f"用户问题：{state['user_query']}\n\n" + "\n".join(evidence_lines)
        try:
            summary = chat(SYSTEM_SUMMARY, user)
        except Exception as e:
            logger.warning("LLM summarize failed: %s", e)
            summary = "根因：信息不足（LLM未配置或调用失败）\n建议：配置OPENAI_*或查看原始日志。\n下一步：补充关键log/寄存器快照。"
        return {**state, "draft_summary": summary}

    return node_fetch, node_parse, node_core, node_tools, node_summarize
