"""P4 gate — support: KB answers + ticket creation with the transcript attached."""
import pytest

from agent import kb
from agent.loop import handle_message
from agent.models import AgentEvent, Session, Ticket
from agent.tools import ToolResult, registry
from agent.tools.base import Tool
from agent.tools.support import AnswerQuestionTool, CreateTicketTool

pytestmark = pytest.mark.django_db


def test_kb_question_answered_from_knowledge_base():
    session = Session.objects.create()
    result = handle_message(session, "what payment methods do you accept?")

    assert result.action["action"] == "kb_answer"
    assert result.action["topic"] == "payment_methods"
    assert "M-Pesa" in result.reply
    assert result.escalated is False
    # An answered question never opens a ticket.
    assert Ticket.objects.count() == 0


def test_kb_answer_comes_from_whitelist_not_model():
    tool = AnswerQuestionTool()
    with pytest.raises(ValueError):
        tool.validate({"topic": "made_up_topic"})
    # The model is only ever offered real knowledge-base topics.
    assert set(tool.input_schema["properties"]["topic"]["enum"]) == set(kb.keys())


def test_request_for_human_opens_ticket_with_transcript():
    session = Session.objects.create()
    session.customer_ref = "edwin@urbantrends.dev"
    session.save()

    handle_message(session, "my landing page keeps crashing on mobile")  # context first
    result = handle_message(session, "I want to speak to a human")

    assert result.action["action"] == "ticket_created"
    assert result.escalated is True

    ticket = Ticket.objects.get()
    assert ticket.status == Ticket.STATUS_OPEN
    assert ticket.reason == Ticket.REASON_AGENT_HANDOFF
    assert ticket.customer_ref == "edwin@urbantrends.dev"
    assert result.action["ticket_ref"] == ticket.ref
    # The transcript is a server-authored snapshot of the conversation so far.
    assert len(ticket.transcript) >= 2
    assert any("speak to a human" in m["text"] for m in ticket.transcript)


def test_ticket_subject_capped_and_category_defaulted():
    tool = CreateTicketTool()
    clean = tool.validate({"subject": "x" * 500})
    assert len(clean["subject"]) == 200
    assert clean["category"] == "other"          # missing category defaults
    coerced = tool.validate({"subject": "help", "category": "nonsense"})
    assert coerced["category"] == "other"        # unknown category coerced, never raises
    with pytest.raises(ValueError):
        tool.validate({"subject": "   "})         # empty subject rejected


def test_loop_escalation_opens_ticket(monkeypatch):
    """When the loop exhausts retries it escalates by opening a ticket (proposal §8)."""

    class BadEcho(Tool):
        name = "echo"

        def validate(self, args):
            return {"text": args.get("text", "")}

        def run(self, args, *, session):
            return ToolResult(ok=True, data={"echoed": "x"}, summary="x")

        def verify(self, args, result):
            return False

    monkeypatch.setattr(registry, "get", lambda name: BadEcho() if name == "echo" else None)

    session = Session.objects.create()
    result = handle_message(session, "please echo")

    assert result.escalated is True
    ticket = Ticket.objects.get()
    assert ticket.reason == Ticket.REASON_VERIFY_EXHAUSTED
    assert result.action["ticket_ref"] == ticket.ref
    # The escalation is recorded in the append-only trail.
    assert session.events.filter(step=AgentEvent.STEP_ERROR).exists()


def test_registry_exposes_support_tools():
    assert {"answer_question", "create_ticket"} <= set(registry.names())
