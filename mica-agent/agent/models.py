"""Data models for the agent service.

`AgentEvent` is the heart of the audit story: an append-only log from which any
session can be fully reconstructed (proposal §6, success metric §10). Nothing
here is ever updated or deleted in normal operation — new rows only.
"""
from __future__ import annotations

import uuid

from django.db import models


class Session(models.Model):
    """One conversation between a visitor and the agent.

    Holds only lightweight state; the authoritative history is the AgentEvent
    log. `customer_ref` is set once a login tool verifies the visitor (P2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_ref = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Session {self.id}"


class Message(models.Model):
    """A single turn in the conversation (what the user and agent said).

    Tool calls and internal loop steps live in AgentEvent, not here; this table
    is just the human-readable transcript the widget renders.
    """

    ROLE_USER = "user"
    ROLE_AGENT = "agent"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_AGENT, "Agent")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.role}: {self.text[:40]}"


class LoginChallenge(models.Model):
    """A pending OTP login for a session (proposal §5 — customer login).

    The code is stored hashed, never in clear. A challenge is single-use, expires
    after a short window, and caps verification attempts. On success the loop
    binds the verified identity onto Session.customer_ref.
    """

    CHANNEL_EMAIL = "email"
    CHANNEL_PHONE = "phone"
    CHANNEL_CHOICES = [(CHANNEL_EMAIL, "Email"), (CHANNEL_PHONE, "Phone")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="challenges")
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES)
    destination = models.CharField(max_length=255, help_text="Email address or phone number")
    code_hash = models.CharField(max_length=255)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_active(self, now=None) -> bool:
        from django.utils import timezone

        now = now or timezone.now()
        return (
            self.consumed_at is None
            and self.attempts < self.max_attempts
            and now < self.expires_at
        )

    def __str__(self) -> str:
        return f"Challenge {self.channel}:{self.destination} for {self.session_id}"


class OrderDraft(models.Model):
    """In-progress order for a session (proposal §5 — the ordering flow).

    Carries the conversation from intent → requirements (form) → server-computed
    quote → confirmation. The `quote` is written only by the pricing engine
    (deterministic money, §8); the model never sets it. At most one non-placed
    draft is active per session.
    """

    STATUS_GATHERING = "gathering"  # form shown, awaiting submission
    STATUS_QUOTED = "quoted"        # quote computed, awaiting confirmation
    STATUS_PLACED = "placed"        # order created from this draft
    STATUS_CHOICES = [
        (STATUS_GATHERING, "Gathering"),
        (STATUS_QUOTED, "Quoted"),
        (STATUS_PLACED, "Placed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="order_drafts")
    service = models.CharField(max_length=64)
    params = models.JSONField(default=dict, blank=True)
    quote = models.JSONField(null=True, blank=True)  # {currency, amount, breakdown}
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_GATHERING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Draft {self.service} ({self.status}) for {self.session_id}"


class Order(models.Model):
    """A placed order, always created in `pending` (proposal §3 non-goals: no
    payment execution in v1). Amount/currency/breakdown are copied from the
    draft's server-computed quote, never from model output.
    """

    STATUS_PENDING = "pending"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="orders")
    customer_ref = models.CharField(max_length=255, blank=True, default="")
    service = models.CharField(max_length=64)
    params = models.JSONField(default=dict)
    currency = models.CharField(max_length=8, default="KES")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    breakdown = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Order {self.service} {self.currency} {self.amount} ({self.status})"


class Ticket(models.Model):
    """A support escalation with the conversation transcript attached (§5, §8).

    Opened when the agent can't resolve a request from the knowledge base, when
    the customer asks for a human, or when the loop exhausts its retries.
    `transcript` is a server-authored snapshot of the Message log — the model
    never writes it. Always starts `open` for a human to action; the agent never
    resolves tickets itself (proposal §8 — escalation path).
    """

    STATUS_OPEN = "open"
    STATUS_CHOICES = [(STATUS_OPEN, "Open")]

    CATEGORY_CHOICES = [
        ("order", "Order"),
        ("billing", "Billing"),
        ("technical", "Technical"),
        ("general", "General"),
        ("other", "Other"),
    ]

    REASON_AGENT_HANDOFF = "agent_handoff"        # the model chose to escalate
    REASON_VERIFY_EXHAUSTED = "verify_exhausted"  # the loop ran out of retries

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="tickets")
    customer_ref = models.CharField(max_length=255, blank=True, default="")
    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="other")
    reason = models.CharField(max_length=32, default=REASON_AGENT_HANDOFF)
    # Server-authored snapshot of the transcript: [{role, text, at}]. Never model-set.
    transcript = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def ref(self) -> str:
        """Short human-facing reference the agent can read back to the customer."""
        return f"UT-{str(self.id)[:8].upper()}"

    def __str__(self) -> str:
        return f"Ticket {self.ref} ({self.category}) for {self.session_id}"


class AgentEvent(models.Model):
    """Append-only record of everything the agent did on a turn.

    Each loop step (act / verify / respond / error) writes one row. `payload` is
    free-form JSON: the intent, tool name, tool args, tool result, verify
    outcome, etc. Ordering by (session, seq) replays the exact sequence.
    """

    STEP_RECEIVE = "receive"
    STEP_ACT = "act"
    STEP_VERIFY = "verify"
    STEP_RESPOND = "respond"
    STEP_ERROR = "error"
    STEP_CHOICES = [
        (STEP_RECEIVE, "Receive"),
        (STEP_ACT, "Act"),
        (STEP_VERIFY, "Verify"),
        (STEP_RESPOND, "Respond"),
        (STEP_ERROR, "Error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="events")
    seq = models.PositiveIntegerField(help_text="Monotonic order of the event within its session")
    step = models.CharField(max_length=16, choices=STEP_CHOICES)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["session", "seq"], name="uniq_event_seq_per_session"),
        ]

    def __str__(self) -> str:
        return f"[{self.seq}] {self.step} @ {self.session_id}"
