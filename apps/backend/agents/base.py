from abc import ABC, abstractmethod
from apps.backend.core.models import ToolResult


class BaseAgent(ABC):
    name: str

    @abstractmethod
    async def run(self, query: str, context: dict) -> ToolResult:
        raise NotImplementedError
