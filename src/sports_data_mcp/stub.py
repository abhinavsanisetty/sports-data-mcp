from __future__ import annotations


class StubServer:
    """Returns not_implemented for every tool call. Used by the eval harness gate check."""

    def call_tool(self, tool_name: str, args: dict) -> dict:
        return {"status": "not_implemented", "tool": tool_name}
