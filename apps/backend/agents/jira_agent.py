from apps.backend.agents.base import BaseAgent
from apps.backend.core.models import ToolResult


class JiraAgent(BaseAgent):
    name = "jira_agent(stub)"

    async def run(self, query: str, context: dict) -> ToolResult:
        return ToolResult(tool=self.name, ok=False, summary="Jira 未接入（占位）", evidences=[])
