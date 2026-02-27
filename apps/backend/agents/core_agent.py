import logging
import re
from typing import Any, Dict, List

from apps.backend.core.config import settings
from apps.backend.core.models import ToolResult
from apps.backend.llm.openai_client import chat

logger = logging.getLogger(__name__)

SYSTEM_FINALIZE = """你是SSD测试日志分析的总控专家（Core Agent Finalizer）。
你会收到：
1) 用户问题
2) 日志解析结果
3) 核心路由决策（为何调用哪些专家）
4) 各专家返回证据

请输出结构化中文结果：
1. 总结（2-5句）
2. 可能根因（<=3条，按可能性排序）
3. 关键证据（引用原文片段）
4. 建议（可执行）
5. 下一步动作（补充信息与复现方案）
要求：证据导向，避免空话；若信息不足明确指出缺口。"""


class CoreAgent:
    """
    Core coordinator:
    - Analyze parsed log + user query
    - Decide which downstream agents should run
    """

    name = "core_agent(orchestrator)"

    async def plan(self, query: str, parsed: Dict[str, Any], raw_log: str = "") -> Dict[str, Any]:
        q = (query or "").lower()
        tokens = (parsed or {}).get("tokens") or {}
        highlights = (parsed or {}).get("highlights") or []

        selected_tools: List[str] = []
        reasons: List[str] = []

        wants_summary_only = any(k in q for k in ["只总结", "仅总结", "summary only", "no rag"])

        needs_spec = any(
            k in q
            for k in [
                "spec",
                "规范",
                "协议",
                "nvme",
                "apst",
                "csts",
                "rdy",
                "timeout",
                "寄存器",
            ]
        ) or bool(tokens.get("mentions_apst") or tokens.get("mentions_csts_rdy") or tokens.get("mentions_timeout"))

        needs_tp = any(
            k in q
            for k in [
                "tp",
                "code",
                "代码",
                "函数",
                "实现",
                "cpp",
                "c++",
                "source",
                "header",
                ".h",
                ".cpp",
            ]
        ) or bool(
            re.search(r"\b(function|module|driver|path)\b", q)
        )

        needs_jira = any(k in q for k in ["jira", "ticket", "issue", "缺陷", "单号"])

        if not wants_summary_only:
            if needs_spec:
                selected_tools.append("spec")
                reasons.append("问题或日志包含规范/协议相关线索，需查Spec RAG。")
            if needs_tp:
                selected_tools.append("tp")
                reasons.append("问题涉及代码实现或函数路径，需查TP RAG。")
            if needs_jira:
                selected_tools.append("jira")
                reasons.append("用户提到缺陷单信息，尝试Jira通道（当前为stub）。")

        # If no explicit route but log has significant error signals, do a minimal RAG route.
        if not selected_tools and not wants_summary_only and highlights:
            selected_tools = ["spec", "tp"]
            reasons.append("存在错误高亮但无明确路由指令，默认拉起Spec+TP做交叉验证。")

        if wants_summary_only:
            reasons.append("用户请求仅总结，跳过RAG子agent。")

        return {
            "selected_tools": selected_tools,
            "reason": " ".join(reasons) if reasons else "未触发子agent，直接进入总结。",
            "need_rag": bool(selected_tools),
            "round_hint": 2,  # downstream expert agents can use this as max rounds hint
        }

    async def finalize(
        self,
        *,
        query: str,
        parsed: Dict[str, Any],
        core_plan: Dict[str, Any],
        expert_reports: List[ToolResult],
    ) -> str:
        lines: List[str] = []
        lines.append("【用户问题】")
        lines.append(query)

        lines.append("\n【核心路由决策】")
        lines.append(
            f"need_rag={core_plan.get('need_rag')} selected_tools={core_plan.get('selected_tools', [])}"
        )
        lines.append(f"reason={core_plan.get('reason', '')}")

        lines.append("\n【日志解析关键线索】")
        for item in (parsed.get("highlights") or [])[:25]:
            lines.append(f"- {item}")

        lines.append("\n【专家回馈】")
        for report in expert_reports:
            lines.append(f"- {report.tool} ok={report.ok}: {report.summary}")
            for ev in report.evidences[:4]:
                lines.append(f"  * ({ev.source}) {ev.snippet}")

        try:
            temperature = settings.openai_finalize_temperature or settings.openai_temperature or None
            return chat(SYSTEM_FINALIZE, "\n".join(lines), temperature=temperature)
        except Exception as e:
            logger.warning("Core finalize failed: %s", e)
            return (
                "总结：信息不足，当前仅能基于有限日志与专家结果给出初步判断。\n"
                "可能根因：1) 控制器就绪超时相关时序问题 2) 低功耗/寄存器配置异常 3) 环境因素导致初始化失败。\n"
                "关键证据：请查看 highlights 与专家证据字段。\n"
                "建议：补充CSTS/CC/APST时序与复现环境差异数据。\n"
                "下一步动作：再次复现并抓取完整寄存器快照。"
            )

    # Backward-compatible alias
    async def run(self, query: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return await self.plan(query, parsed)
