from apps.backend.agents.base import BaseAgent
from apps.backend.core.models import ToolResult, Evidence
from apps.backend.tools.dify_client import DifyClient, dify_text_and_citations


class SpecAgent(BaseAgent):
    name = "spec_agent(dify)"

    def __init__(self, client: DifyClient):
        self.client = client

    async def run(self, query: str, context: dict) -> ToolResult:
        max_rounds = max(1, min(int(context.get("round_hint", 1) or 1), 3))
        base_prompt = (
            "你是SSD/NVMe规范助手。请基于知识库回答问题，并给出可引用证据（尽量包含原文片段、章节或术语）。\n"
            f"问题：{query}\n"
            f"上下文tokens：{context.get('tokens')}\n"
        )

        evidences = []
        rounds_used = 0
        last_error = ""

        for round_idx in range(max_rounds):
            rounds_used = round_idx + 1
            prompt = base_prompt
            if round_idx > 0:
                prompt += (
                    "\n上一轮证据不足。请更聚焦到：直接相关的规范条款、关键术语解释、以及可验证的文本片段。"
                )
            try:
                resp = await self.client.ask(prompt)
            except Exception as e:
                last_error = str(e)
                continue

            text, cites = dify_text_and_citations(resp)
            if cites:
                evidences = [
                    Evidence(source="dify(spec)", snippet=str(c.get("quote") or c.get("content") or c), meta=c)
                    for c in cites[:6]
                ]
                break

            if text.strip():
                evidences = [Evidence(source="dify(spec)", snippet=text[:500], meta={"note": "no citations field"})]
                if len(text.strip()) >= 80:
                    break

        if not evidences:
            return ToolResult(
                tool=self.name,
                ok=False,
                summary=f"Spec检索失败：{last_error or '未返回有效证据'}",
                evidences=[],
            )

        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Dify Spec 知识库检索完成（rounds={rounds_used}）",
            evidences=evidences,
        )
