from abc import ABC, abstractmethod


class ToolResult:
    __slots__ = ("id", "output", "is_error")

    def __init__(self, tool_call_id, output, is_error=False):
        self.id = tool_call_id
        self.output = output
        self.is_error = is_error


class Tool(ABC):
    name = ""
    description = ""
    parameters = {}

    @abstractmethod
    def execute(self, params):
        raise NotImplementedError

    def get_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

