"""Tool contract and registry.

Guardrail (proposal §8): the model may only ever call whitelisted tools, and
every tool re-validates its own input server-side regardless of what the model
sends. A Tool therefore owns three things: its Claude-facing JSON schema, an
input validator, and the actual side-effecting `run`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolResult:
    """Outcome of running a tool, consumed by the loop's verify step."""

    ok: bool
    data: dict[str, Any]
    # Human-facing summary the agent can fold into its reply.
    summary: str = ""
    # Machine-readable reason when ok is False (drives retry vs escalate).
    error: str = ""


class Tool:
    """Base class for every action the agent can take.

    Subclasses set `name`, `description`, `input_schema` (JSON Schema for
    Claude tool use) and implement `validate` + `run`.
    """

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return cleaned args or raise ValueError. Never trust raw model input."""
        return args

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        raise NotImplementedError

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        """Did the tool achieve the caller's intent? (loop's verify step)

        Default: trust the tool's own `ok` flag — i.e. "did it execute without
        failure". Override to add an intent check that inspects `result.data`.
        Note the distinction: a tool can succeed (`ok=True`) yet report a
        negative *business* outcome in its data (e.g. a wrong OTP); that is a
        verified run, not a failure, and must not trigger retry/escalation.
        """
        return bool(result.ok)

    def spec(self) -> dict[str, Any]:
        """The tool definition passed to the Anthropic API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Whitelist of callable tools, keyed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if not tool.name:
            raise ValueError("Tool must define a name")
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        return [tool.spec() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)


# Process-wide registry. Tool modules register onto this at import time
# (see agent.apps.AgentConfig.ready).
registry = ToolRegistry()


def register(tool_cls: Callable[[], Tool]) -> Callable[[], Tool]:
    """Class decorator: instantiate and register a Tool subclass."""
    registry.register(tool_cls())
    return tool_cls
