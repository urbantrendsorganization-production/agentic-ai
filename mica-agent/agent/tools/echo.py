"""The single dummy tool for P1.

It does nothing risky — just echoes text back — but it exercises the whole
loop: the model picks it, the loop runs it, the verify step confirms the echoed
text matches what was requested, and the outcome is logged. Real capabilities
(login, navigate, order, form, ticket) land in P2–P4 using this same contract.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult, register


@register
class EchoTool(Tool):
    name = "echo"
    description = (
        "Echo a short piece of text back to the user. Use this to acknowledge or "
        "repeat what the user said. This is a placeholder capability for the pilot."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to echo back to the user.",
            }
        },
        "required": ["text"],
    }

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("echo requires a non-empty 'text' string")
        # Cap length server-side; never trust the model's input size.
        return {"text": text.strip()[:500]}

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        text = args["text"]
        return ToolResult(
            ok=True,
            data={"echoed": text},
            summary=text,
        )

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        # Intent check: the text actually echoed matches what we asked for.
        return result.ok and result.data.get("echoed") == args.get("text")
