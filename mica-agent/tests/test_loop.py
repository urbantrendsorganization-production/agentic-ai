"""P1 gate: prove wait → act → verify → respond → log end-to-end.

All tests run against the deterministic StubPlanner and the single `echo` tool.
"""
import pytest

from agent.loop import handle_message
from agent.models import AgentEvent, Message, Session
from agent.planner import Decision, StubPlanner
from agent.tools import ToolResult, registry
from agent.tools.base import Tool

pytestmark = pytest.mark.django_db


def test_happy_path_runs_full_loop():
    session = Session.objects.create()

    result = handle_message(session, "hello there")

    # respond: the echo tool's summary comes back as the reply.
    assert result.reply == "hello there"
    assert result.escalated is False

    # log: the append-only trail records the whole loop in order.
    steps = list(session.events.order_by("seq").values_list("seq", "step"))
    assert steps == [
        (1, AgentEvent.STEP_RECEIVE),
        (2, AgentEvent.STEP_ACT),
        (3, AgentEvent.STEP_VERIFY),
        (4, AgentEvent.STEP_RESPOND),
    ]
    # transcript: one user turn, one agent turn.
    roles = list(session.messages.order_by("created_at").values_list("role", flat=True))
    assert roles == [Message.ROLE_USER, Message.ROLE_AGENT]


def test_verify_step_confirms_tool_outcome():
    session = Session.objects.create()
    handle_message(session, "check me")

    verify = session.events.get(step=AgentEvent.STEP_VERIFY)
    assert verify.payload["ok"] is True
    assert verify.payload["result"]["echoed"] == "check me"


def test_seq_is_monotonic_across_turns():
    session = Session.objects.create()
    handle_message(session, "first")
    handle_message(session, "second")

    seqs = list(session.events.order_by("seq").values_list("seq", flat=True))
    assert seqs == [1, 2, 3, 4, 5, 6, 7, 8]  # 4 events per turn, no gaps/dupes


def test_registry_exposes_whitelisted_tools():
    # echo is the P1 tool; the full P2 set is asserted in test_navigate.py.
    assert "echo" in registry.names()


def test_verify_failure_escalates(monkeypatch):
    """A tool that never satisfies verify exhausts retries and escalates."""

    class BadEcho(Tool):
        name = "echo"

        def validate(self, args):
            return {"text": args.get("text", "")}

        def run(self, args, *, session):
            return ToolResult(ok=True, data={"echoed": "WRONG"}, summary="x")

        def verify(self, args, result):
            # Tool executed, but never satisfies the intent check → keeps failing.
            return False

    monkeypatch.setattr(registry, "get", lambda name: BadEcho() if name == "echo" else None)

    session = Session.objects.create()
    result = handle_message(session, "please echo")

    assert result.escalated is True
    # No final successful verify; the loop logged repeated failures then escalated.
    verifies = session.events.filter(step=AgentEvent.STEP_VERIFY)
    assert verifies.exists()
    assert all(v.payload["ok"] is False for v in verifies)
    assert session.events.filter(step=AgentEvent.STEP_RESPOND).exists()


def test_stub_planner_routes_to_echo():
    planner = StubPlanner()
    decision = planner.decide(user_text="hi", tool_specs=[], history=[])
    assert decision.kind == "tool"
    assert decision.tool_name == "echo"
    assert decision.tool_args == {"text": "hi"}


class _UsagePlanner:
    """A planner that reports token usage each call — stands in for real Claude."""

    def __init__(self, usage):
        self._usage = usage
        self.calls = 0

    def decide(self, *, user_text, tool_specs, history):
        self.calls += 1
        return Decision(kind="tool", tool_name="echo",
                        tool_args={"text": user_text}, usage=dict(self._usage))

    def compose_reply(self, *, tool_summary, history):
        return tool_summary or "Done."


def test_stub_planner_reports_no_usage():
    """The keyless stub runs no model, so the turn carries no cost (P6)."""
    session = Session.objects.create()
    result = handle_message(session, "hello")

    assert result.usage is None
    respond = session.events.get(step=AgentEvent.STEP_RESPOND)
    assert respond.payload["usage"] is None


def test_planner_usage_is_logged_and_returned(monkeypatch):
    """A model call's token usage lands on the act + respond events and TurnResult."""
    from agent import loop as loop_mod

    planner = _UsagePlanner({"model": "claude-sonnet-4-6", "input_tokens": 12, "output_tokens": 5})
    monkeypatch.setattr(loop_mod, "get_planner", lambda: planner)

    session = Session.objects.create()
    result = handle_message(session, "hello")

    assert result.usage == {
        "model": "claude-sonnet-4-6", "input_tokens": 12, "output_tokens": 5, "calls": 1,
    }
    act = session.events.get(step=AgentEvent.STEP_ACT)
    assert act.payload["usage"]["input_tokens"] == 12
    respond = session.events.get(step=AgentEvent.STEP_RESPOND)
    assert respond.payload["usage"]["calls"] == 1


def test_usage_accumulates_across_retries(monkeypatch):
    """Retries before escalation each cost tokens; the turn total sums them (P6)."""
    from agent import loop as loop_mod

    class BadEcho(Tool):
        name = "echo"

        def validate(self, args):
            return {"text": args.get("text", "")}

        def run(self, args, *, session):
            return ToolResult(ok=True, data={"echoed": "WRONG"}, summary="x")

        def verify(self, args, result):
            return False  # never satisfies intent → loop retries then escalates

    monkeypatch.setattr(registry, "get", lambda name: BadEcho() if name == "echo" else None)
    planner = _UsagePlanner({"input_tokens": 10, "output_tokens": 4})
    monkeypatch.setattr(loop_mod, "get_planner", lambda: planner)

    session = Session.objects.create()
    result = handle_message(session, "please echo")

    assert result.escalated is True
    assert planner.calls > 1  # it actually retried
    assert result.usage["calls"] == planner.calls
    assert result.usage["input_tokens"] == 10 * planner.calls
    assert result.usage["output_tokens"] == 4 * planner.calls
