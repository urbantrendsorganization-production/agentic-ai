"""Tool package. Importing it registers every tool onto the shared registry."""
from .base import Tool, ToolRegistry, ToolResult, registry
from .echo import EchoTool
from .login import RequestLoginCodeTool, VerifyLoginCodeTool
from .navigate import NavigateTool
from .order import CreateOrderTool, StartOrderTool
from .support import AnswerQuestionTool, CreateTicketTool

__all__ = [
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "registry",
    "EchoTool",
    "RequestLoginCodeTool",
    "VerifyLoginCodeTool",
    "NavigateTool",
    "StartOrderTool",
    "CreateOrderTool",
    "AnswerQuestionTool",
    "CreateTicketTool",
]
