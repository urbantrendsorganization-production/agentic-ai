"""Deep-link navigation (proposal §5 — site navigation).

Read-only: the tool computes *where* to go from the whitelisted site map and
returns a site-relative path. The widget performs the actual client-side
navigation. The model may only choose a known destination key, so it can never
point a visitor at an arbitrary URL.
"""
from __future__ import annotations

from typing import Any

from .. import sitemap
from .base import Tool, ToolResult, register


@register
class NavigateTool(Tool):
    name = "navigate"
    description = (
        "Take the customer to a specific page on the site when they ask where to "
        "find something or want to go somewhere. Choose the closest destination."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "Which page to navigate the customer to.",
            }
        },
        "required": ["destination"],
    }

    def spec(self) -> dict[str, Any]:
        # Enum filled per turn from the active sitemap (may be backend-sourced),
        # so no network call at import time. spec() is what's sent to the model.
        schema = {
            "type": "object",
            "properties": {
                "destination": dict(
                    self.input_schema["properties"]["destination"], enum=sitemap.keys()
                ),
            },
            "required": ["destination"],
        }
        return {"name": self.name, "description": self.description, "input_schema": schema}

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        key = (args.get("destination") or "").strip().lower()
        if sitemap.resolve(key) is None:
            raise ValueError(f"unknown destination: {key!r}")
        return {"destination": key}

    def run(self, args: dict[str, Any], *, session) -> ToolResult:
        dest = sitemap.resolve(args["destination"])
        return ToolResult(
            ok=True,
            # `navigate` is the client-side action the widget executes.
            data={"action": "navigate", "path": dest.path, "label": dest.label},
            summary=f"Taking you to {dest.label} — {dest.path}",
        )

    def verify(self, args: dict[str, Any], result: ToolResult) -> bool:
        # Intent check: we resolved to a real, whitelisted path.
        return result.ok and result.data.get("path") in sitemap.paths()
