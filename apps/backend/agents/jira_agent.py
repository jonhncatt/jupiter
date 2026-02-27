import inspect
from typing import Optional

from apps.backend.agents.base import BaseAgent
from apps.backend.core.models import ToolResult, Evidence
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

        prompt = (
            "你是Jira缺陷知识助手。请基于Jira知识库返回与问题相关的缺陷信息，"
            "优先包含：单号、标题、状态、根因描述、修复建议或关联记录。\n"
            f"问题：{query}\n"
            f"上下文highlights：{context.get('highlights')}\n"
            f"PCB console: {((context.get('domain_context') or {}).get('pcb_console') or {}).get('status_line')}\n"
        )
        await emit("agent.round", {"round": 1, "status": "started", "query_preview": query[:200]})
        try:
            resp = await self.client.ask(prompt)
        except Exception as e:
            await emit("agent.round", {"round": 1, "status": "error", "error": str(e)[:500]})
            return ToolResult(
                tool=self.name,
                ok=False,
                summary=f"Jira检索失败：{e}",
                evidences=[],
                debug={"status": "error", "prompt_preview": prompt[:500], "error": str(e)[:500]},
            )

        text, cites = dify_text_and_citations(resp)
        evidences = []
        if cites:
            evidences = [
                Evidence(source="dify(jira)", snippet=str(c.get("quote") or c.get("content") or c), meta=c)
                for c in cites[:6]
            ]
        elif text.strip():
            evidences = [Evidence(source="dify(jira)", snippet=text[:500], meta={"note": "no citations field"})]

        debug = {
            "status": "ok",
            "prompt_preview": prompt[:500],
            "answer_preview": text[:500],
            "citations_count": len(cites),
        }
        await emit(
            "agent.round",
            {"round": 1, "status": "ok", "citations_count": len(cites), "answer_preview": text[:300]},
        )

        if not evidences:
            return ToolResult(
                tool=self.name,
                ok=False,
                summary="Jira检索未返回有效证据",
                evidences=[],
                debug=debug,
            )

        return ToolResult(tool=self.name, ok=True, summary="Dify Jira 知识库检索完成", evidences=evidences, debug=debug)
