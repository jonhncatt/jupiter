from apps.backend.agents.base import BaseAgent
from apps.backend.core.models import ToolResult, Evidence
from apps.backend.tools.dify_client import DifyClient, dify_text_and_citations


class TpAgent(BaseAgent):
    name = "tp_agent(dify)"

    def __init__(self, client: DifyClient):
        self.client = client

    async def run(self, query: str, context: dict) -> ToolResult:
        prompt = (
            "你是测试源代码/测试元代码助手（TP）。请从知识库（代码、头文件、实现）中找出与问题最相关的函数/逻辑，"
            "并输出：函数名、关键代码片段、解释。\n"
            f"问题：{query}\n"
            f"上下文：{context.get('highlights')}\n"
        )
        resp = await self.client.ask(prompt)
        text, cites = dify_text_and_citations(resp)

        evidences = []
        if cites:
            for c in cites[:6]:
                evidences.append(
                    Evidence(source="dify(tp)", snippet=str(c.get("quote") or c.get("content") or c), meta=c)
                )
        else:
            evidences.append(Evidence(source="dify(tp)", snippet=text[:500], meta={"note": "no citations field"}))

        return ToolResult(tool=self.name, ok=True, summary="Dify TP 知识库检索完成", evidences=evidences)
