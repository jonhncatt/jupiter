from apps.backend.agents.base import BaseAgent
from apps.backend.core.models import ToolResult, Evidence
from apps.backend.tools.dify_client import DifyClient, dify_text_and_citations


class TpAgent(BaseAgent):
    name = "tp_agent(dify)"

    def __init__(self, client: DifyClient):
        self.client = client

    async def run(self, query: str, context: dict) -> ToolResult:
        max_rounds = max(1, min(int(context.get("round_hint", 1) or 1), 3))
        base_prompt = (
            "你是测试源代码/测试元代码助手（TP）。请从知识库（代码、头文件、实现）中定位相关函数/逻辑，"
            "输出：函数名、关键代码片段、解释。\n"
            f"问题：{query}\n"
            f"上下文：{context.get('highlights')}\n"
        )

        evidences = []
        rounds_used = 0
        last_error = ""

        for round_idx in range(max_rounds):
            rounds_used = round_idx + 1
            prompt = base_prompt
            if round_idx > 0:
                prompt += "\n上一轮结果不够精确。请优先返回函数名、文件路径、以及直接相关代码语义。"
            try:
                resp = await self.client.ask(prompt)
            except Exception as e:
                last_error = str(e)
                continue

            text, cites = dify_text_and_citations(resp)
            if cites:
                evidences = [
                    Evidence(source="dify(tp)", snippet=str(c.get("quote") or c.get("content") or c), meta=c)
                    for c in cites[:6]
                ]
                break

            if text.strip():
                evidences = [Evidence(source="dify(tp)", snippet=text[:500], meta={"note": "no citations field"})]
                if len(text.strip()) >= 80:
                    break

        if not evidences:
            return ToolResult(
                tool=self.name,
                ok=False,
                summary=f"TP检索失败：{last_error or '未返回有效证据'}",
                evidences=[],
            )

        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Dify TP 知识库检索完成（rounds={rounds_used}）",
            evidences=evidences,
        )
