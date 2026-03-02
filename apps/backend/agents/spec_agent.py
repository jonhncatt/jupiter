import inspect

from apps.backend.agents.base import BaseAgent
from apps.backend.agents.retrieval_utils import (
    build_anchor_terms,
    compact_items,
    evidence_is_sufficient,
    evidence_score,
    unique_strings,
)
from apps.backend.core.models import ToolResult, Evidence
from apps.backend.prompts.log_analysis_skill import SPEC_EXPERT_PLAYBOOK
from apps.backend.tools.dify_client import DifyClient, dify_text_and_citations


class SpecAgent(BaseAgent):
    name = "spec_agent(dify)"

    def __init__(self, client: DifyClient):
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

        max_rounds = max(1, min(int(context.get("round_hint", 1) or 1), 4))
        domain = context.get("domain_context") or {}
        pcb = domain.get("pcb_console") or {}
        nvmecore = domain.get("nvmecore") or {}
        command_lines = compact_items(nvmecore.get("command_lines", []), limit=12)
        anchors = build_anchor_terms(
            [query, pcb.get("status"), pcb.get("test_name"), pcb.get("revision"), pcb.get("script_line")],
            context.get("tokens", {}).keys(),
            command_lines,
            limit=12,
        )
        retrieval_queries = _build_spec_retrieval_queries(query=query, pcb=pcb, command_lines=command_lines, anchors=anchors)

        best: dict | None = None
        last_error = ""
        round_traces = []

        for round_idx, retrieval_query in enumerate(retrieval_queries[:max_rounds], start=1):
            prompt = _build_spec_prompt(
                user_query=query,
                retrieval_query=retrieval_query,
                command_lines=command_lines,
                pcb=pcb,
                tokens=context.get("tokens", {}),
                anchors=anchors,
                retry_note="上一轮证据不足，请更聚焦直接条款、术语和命令返回解释。"
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
                summary=f"Spec检索失败：{last_error or '未返回有效证据'}",
                evidences=[],
                debug={"rounds": round_traces, "retrieval_queries": retrieval_queries[:max_rounds]},
            )

        evidences = _to_evidences("dify(spec)", best["text"], best["cites"])
        if not evidences:
            return ToolResult(
                tool=self.name,
                ok=False,
                summary=f"Spec检索失败：{last_error or '未返回有效证据'}",
                evidences=[],
                debug={"rounds": round_traces, "retrieval_queries": retrieval_queries[:max_rounds]},
            )

        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Dify Spec 知识库检索完成（queries={min(len(retrieval_queries), max_rounds)}）",
            evidences=evidences,
            debug={
                "rounds": round_traces,
                "retrieval_queries": retrieval_queries[:max_rounds],
                "selected_query": best["retrieval_query"],
                "evidence_score": best["score"],
                "strategy": "retrieval-first-multi-query",
            },
        )


def _build_spec_retrieval_queries(*, query: str, pcb: dict, command_lines: list[str], anchors: list[str]) -> list[str]:
    base = [
        " ".join(["NVMe spec", pcb.get("status") or "", pcb.get("test_name") or "", *command_lines[:4]]).strip(),
        " ".join(["CSTS RDY timeout", *command_lines[:3]]).strip(),
        " ".join(["completion status command meaning", *command_lines[:4]]).strip(),
        " ".join([query, *anchors[:6]]).strip(),
    ]
    if pcb.get("status_line"):
        base.append(f"规范解释 {pcb.get('status_line')}")
    return unique_strings(base)


def _build_spec_prompt(
    *,
    user_query: str,
    retrieval_query: str,
    command_lines: list[str],
    pcb: dict,
    tokens: dict,
    anchors: list[str],
    retry_note: str,
) -> str:
    return (
        SPEC_EXPERT_PLAYBOOK.strip()
        + "\n\n你当前执行的是 Spec 检索，不是普通聊天。先基于知识库召回最相关的规范证据，再做简短解释。\n"
        f"用户问题：{user_query}\n"
        f"检索目标：{retrieval_query}\n"
        f"检索锚点：{', '.join(anchors[:10])}\n"
        f"上下文tokens：{tokens}\n"
        f"PCB状态：status={pcb.get('status')} test={pcb.get('test_name')} rev={pcb.get('revision')} line={pcb.get('script_line')}\n"
        "nvmecore关键命令/回复：\n"
        + "\n".join(command_lines)
        + "\n输出要求：\n"
        "1) 直接相关的规范术语/条款/命令解释\n"
        "2) 这些命令或返回是否异常，为什么\n"
        "3) 尽量给原文片段或 citation，不要泛泛而谈\n"
        + (f"{retry_note}\n" if retry_note else "")
    )


def _to_evidences(source: str, text: str, cites: list[dict]) -> list[Evidence]:
    if cites:
        return [Evidence(source=source, snippet=str(c.get("quote") or c.get("content") or c), meta=c) for c in cites[:6]]
    if text.strip():
        return [Evidence(source=source, snippet=text[:500], meta={"note": "no citations field"})]
    return []
