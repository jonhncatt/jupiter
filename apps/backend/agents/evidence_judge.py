from __future__ import annotations

from typing import Any, Dict, List

from apps.backend.core.models import ToolResult


class EvidenceJudge:
    name = "evidence_judge"

    def evaluate(
        self,
        *,
        selected_tools: List[str],
        latest_tool_results: List[ToolResult],
        prior_queries: Dict[str, str],
        retry_count: int,
        max_retry_count: int,
    ) -> Dict[str, Any]:
        if not selected_tools:
            return {
                "enough": True,
                "retry": False,
                "retry_tools": [],
                "retry_queries": {},
                "reason": "当前无需调用 experts。",
                "details": [],
            }

        result_by_tool = {result.tool: result for result in latest_tool_results}
        retry_tools: List[str] = []
        retry_queries: Dict[str, str] = {}
        details: List[Dict[str, Any]] = []

        for tool in selected_tools:
            result = result_by_tool.get(_tool_runtime_name(tool))
            if result is None:
                retry_tools.append(tool)
                retry_queries[tool] = _rewrite_query(tool, prior_queries.get(tool, ""), "缺少该 expert 返回结果")
                details.append({"tool": tool, "status": "missing", "reason": "missing_result"})
                continue

            score = int((result.debug or {}).get("evidence_score") or 0)
            ok = bool(result.ok)
            citations_count = _best_citations_count(result.debug or {})
            evidence_count = len(result.evidences or [])
            reason = _insufficient_reason(tool, ok=ok, score=score, citations_count=citations_count, evidence_count=evidence_count, result=result)
            if reason:
                retry_tools.append(tool)
                retry_queries[tool] = _rewrite_query(tool, prior_queries.get(tool, ""), reason)
                details.append(
                    {
                        "tool": tool,
                        "status": "retry",
                        "reason": reason,
                        "score": score,
                        "citations_count": citations_count,
                        "evidence_count": evidence_count,
                    }
                )
            else:
                details.append(
                    {
                        "tool": tool,
                        "status": "enough",
                        "score": score,
                        "citations_count": citations_count,
                        "evidence_count": evidence_count,
                    }
                )

        if retry_tools and retry_count < max_retry_count:
            return {
                "enough": False,
                "retry": True,
                "retry_tools": retry_tools,
                "retry_queries": retry_queries,
                "reason": "部分 expert 证据不足，需要重试。",
                "details": details,
            }

        return {
            "enough": True,
            "retry": False,
            "retry_tools": retry_tools,
            "retry_queries": retry_queries,
            "reason": "达到重试上限，或所有 expert 证据已足够。",
            "details": details,
            "stopped_by_retry_limit": bool(retry_tools),
        }


def _tool_runtime_name(tool: str) -> str:
    return {
        "spec": "spec_agent(dify)",
        "tp": "tp_agent(dify)",
        "jira": "jira_agent(dify)",
    }.get(tool, tool)


def _best_citations_count(debug: Dict[str, Any]) -> int:
    rounds = debug.get("rounds") or []
    best = 0
    for item in rounds:
        if isinstance(item, dict):
            best = max(best, int(item.get("citations_count") or 0))
    return max(best, int(debug.get("citations_count") or 0))


def _insufficient_reason(
    tool: str,
    *,
    ok: bool,
    score: int,
    citations_count: int,
    evidence_count: int,
    result: ToolResult,
) -> str:
    if not ok:
        return "expert 调用失败"
    if evidence_count == 0:
        return "没有返回证据"
    if score < 5:
        return "证据分数偏低"
    joined = " ".join(ev.snippet for ev in result.evidences[:3]).lower()
    if tool == "spec" and citations_count < 1:
        return "缺少规范引用"
    if tool == "tp" and not any(token in joined for token in [".c", ".cpp", ".h", "/", "function", "函数", "path", "路径"]):
        return "缺少代码路径或函数定位"
    if tool == "jira" and not any(token in joined for token in ["jira-", "bug", "issue", "缺陷", "单", "ticket"]):
        return "缺少历史缺陷标识"
    return ""


def _rewrite_query(tool: str, base_query: str, reason: str) -> str:
    prefix = {
        "spec": "请只返回最直接相关的规范条款、术语解释、命令含义和原文片段。",
        "tp": "请只返回最相关的函数名、文件路径、脚本行号附近逻辑和代码语义。",
        "jira": "请只返回最相似的历史缺陷单号、处理方式、结论和关联记录。",
    }.get(tool, "请更聚焦直接证据。")
    return f"{prefix}\n上一轮不足原因：{reason}\n继续任务：{base_query}".strip()
