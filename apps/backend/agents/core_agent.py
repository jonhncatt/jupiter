import re
from typing import Any, Dict, List


class CoreAgent:
    """
    Core coordinator:
    - Analyze parsed log + user query
    - Decide which downstream agents should run
    """

    name = "core_agent(router)"

    async def run(self, query: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
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
        }
