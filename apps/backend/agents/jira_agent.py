import inspect
from typing import Optional

from apps.backend.agents.base import BaseAgent
from apps.backend.agents.retrieval_utils import (
    build_anchor_terms,
    compact_items,
    evidence_is_sufficient,
    evidence_score,
    unique_strings,
)
from apps.backend.core.models import ToolResult, Evidence
from apps.backend.prompts.log_analysis_skill import JIRA_EXPERT_PLAYBOOK
from apps.backend.tools.dify_client import DifyClient, dify_text_and_citations


class JiraAgent(BaseAgent):
    name = "jira_agent(dify)"

    def __init__(self, client: Optional[DifyClient] = None):
        self.client = client

    async def run(self, query: str, context: dict) -> ToolResult:
        async def emit(event_type: str, payload: dict) -> None:
            cb = context.get("event_callback")
            if not cb:
                return
            out = cb(
                {
                    "type": event_type,
                    "payload": {
                        "agent": self.name,
                        "run_id": context.get("run_id"),
                        **payload,
                    },
                }
            )
            if inspect.isawaitable(out):
                await out

        if self.client is None:
            await emit("agent.round", {"round": 1, "status": "error", "error": "jira client not configured"})
            return ToolResult(
                tool=self.name,
                ok=False,
                summary="Jira RAG 未配置（缺少 Dify client）",
                evidences=[],
                debug={"status": "not_configured"},
            )

        domain = context.get("domain_context") or {}
        pcb = domain.get("pcb_console") or {}
        nvmecore = domain.get("nvmecore") or {}
        highlights = compact_items(context.get("highlights", []), limit=8)
        command_lines = compact_items(nvmecore.get("command_lines", []), limit=6)
        anchors = build_anchor_terms(
            [query, pcb.get("status"), pcb.get("test_name"), pcb.get("revision"), pcb.get("status_line")],
            highlights,
            command_lines,
            limit=12,
        )
        max_rounds = max(1, min(int(context.get("round_hint", 1) or 1), 3))
        retrieval_queries = _build_jira_retrieval_queries(query=query, pcb=pcb, highlights=highlights, command_lines=command_lines)

        best: dict | None = None
        last_error = ""
        round_traces = []

        for round_idx, retrieval_query in enumerate(retrieval_queries[:max_rounds], start=1):
            prompt = _build_jira_prompt(
                user_query=query,
                retrieval_query=retrieval_query,
                pcb=pcb,
                highlights=highlights,
                command_lines=command_lines,
                anchors=anchors,
                retry_note="上一轮匹配不够可信。请更聚焦相似失败签名、处理方式和结论。"
                if round_idx > 1
                else "",
            )
            await emit(
                "agent.round",
                {
                    "round": round_idx,
                    "status": "started",
                    "query_preview": query[:200],
                    "retrieval_query": retrieval_query[:220],
                },
            )
            try:
                resp = await self.client.ask(prompt)
            except Exception as e:
                last_error = str(e)
                round_traces.append(
                    {
                        "round": round_idx,
                        "status": "error",
                        "retrieval_query": retrieval_query,
                        "prompt_preview": prompt[:500],
                        "error": last_error[:500],
                    }
                )
                await emit(
                    "agent.round",
                    {
                        "round": round_idx,
                        "status": "error",
                        "retrieval_query": retrieval_query[:220],
                        "error": last_error[:500],
                    },
                )
                continue

            text, cites = dify_text_and_citations(resp)
            score = evidence_score(text=text, citations=cites, anchors=anchors)
            attempt = {
                "round": round_idx,
                "status": "ok",
                "retrieval_query": retrieval_query,
                "prompt_preview": prompt[:500],
                "answer_preview": text[:500],
                "citations_count": len(cites),
                "evidence_score": score,
            }
            round_traces.append(attempt)
            await emit(
                "agent.round",
                {
                    "round": round_idx,
                    "status": "ok",
                    "retrieval_query": retrieval_query[:220],
                    "citations_count": len(cites),
                    "evidence_score": score,
                    "answer_preview": text[:300],
                },
            )
            if best is None or score > best["score"]:
                best = {"score": score, "text": text, "cites": cites, "retrieval_query": retrieval_query}
            if evidence_is_sufficient(score=score, citations=cites, text=text):
                break

        if best is None:
            return ToolResult(
                tool=self.name,
                ok=False,
                summary=f"Jira检索失败：{last_error or '未返回有效证据'}",
                evidences=[],
                debug={"rounds": round_traces, "retrieval_queries": retrieval_queries[:max_rounds]},
            )

        evidences = _to_evidences("dify(jira)", best["text"], best["cites"])
        if not evidences:
            return ToolResult(
                tool=self.name,
                ok=False,
                summary=f"Jira检索失败：{last_error or '未返回有效证据'}",
                evidences=[],
                debug={"rounds": round_traces, "retrieval_queries": retrieval_queries[:max_rounds]},
            )

        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Dify Jira 知识库检索完成（queries={min(len(retrieval_queries), max_rounds)}）",
            evidences=evidences,
            debug={
                "rounds": round_traces,
                "retrieval_queries": retrieval_queries[:max_rounds],
                "selected_query": best["retrieval_query"],
                "evidence_score": best["score"],
                "strategy": "retrieval-first-multi-query",
            },
        )


def _build_jira_retrieval_queries(*, query: str, pcb: dict, highlights: list[str], command_lines: list[str]) -> list[str]:
    base = [
        " ".join([pcb.get("status_line") or "", pcb.get("test_name") or "", "jira"]).strip(),
        " ".join([query, pcb.get("test_name") or "", pcb.get("revision") or "", pcb.get("status") or ""]).strip(),
        " ".join([*command_lines[:3], "similar issue"]).strip(),
        " ".join([*highlights[:2], "historical fix"]).strip(),
    ]
    return unique_strings(base)


def _build_jira_prompt(
    *,
    user_query: str,
    retrieval_query: str,
    pcb: dict,
    highlights: list[str],
    command_lines: list[str],
    anchors: list[str],
    retry_note: str,
) -> str:
    return (
        JIRA_EXPERT_PLAYBOOK.strip()
        + "\n\n你当前执行的是 Jira 检索，不是普通聊天。先召回相似缺陷，再总结处理方式。\n"
        f"用户问题：{user_query}\n"
        f"检索目标：{retrieval_query}\n"
        f"检索锚点：{', '.join(anchors[:10])}\n"
        f"失败摘要：{pcb.get('status_line')}\n"
        "错误高亮：\n"
        + "\n".join(highlights)
        + "\n相关命令/返回：\n"
        + "\n".join(command_lines)
        + "\n输出要求：\n"
        "1) 最相似的缺陷单/记录\n"
        "2) 当时如何处理、最后结论是什么\n"
        "3) 如果没有可信匹配，直接说未命中\n"
        + (f"{retry_note}\n" if retry_note else "")
    )


def _to_evidences(source: str, text: str, cites: list[dict]) -> list[Evidence]:
    if cites:
        return [Evidence(source=source, snippet=str(c.get("quote") or c.get("content") or c), meta=c) for c in cites[:6]]
    if text.strip():
        return [Evidence(source=source, snippet=text[:500], meta={"note": "no citations field"})]
    return []
