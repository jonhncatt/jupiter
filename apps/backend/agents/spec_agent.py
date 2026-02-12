from apps.backend.agents.base import BaseAgent
from apps.backend.core.models import ToolResult, Evidence
from apps.backend.tools.dify_client import DifyClient, dify_text_and_citations


class SpecAgent(BaseAgent):
    name = "spec_agent(dify)"

    def __init__(self, client: DifyClient):
        self.client = client

    async def run(self, query: str, context: dict) -> ToolResult:
        prompt = (
            "你是SSD/NVMe规范助手。请基于知识库回答问题，并给出可引用的证据片段（越具体越好）。\n"
            f"问题：{query}\n"
            f"上下文tokens：{context.get('tokens')}\n"
        )
        resp = await self.client.ask(prompt)
        text, cites = dify_text_and_citations(resp)

        evidences = []
        if cites:
            for c in cites[:6]:
                evidences.append(
                    Evidence(source="dify(spec)", snippet=str(c.get("quote") or c.get("content") or c), meta=c)
                )
        else:
            # 没 citations 也给一条“回答摘要”作为证据
            evidences.append(Evidence(source="dify(spec)", snippet=text[:500], meta={"note": "no citations field"}))

        return ToolResult(tool=self.name, ok=True, summary="Dify Spec 知识库检索完成", evidences=evidences)
