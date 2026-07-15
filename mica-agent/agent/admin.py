from django.contrib import admin

from .models import AgentEvent, LoginChallenge, Message, Order, OrderDraft, Session, Ticket


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_ref", "created_at")
    readonly_fields = ("id", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "text", "created_at")
    list_filter = ("role",)


@admin.register(LoginChallenge)
class LoginChallengeAdmin(admin.ModelAdmin):
    list_display = ("session", "channel", "destination", "attempts", "expires_at", "consumed_at")
    list_filter = ("channel",)
    # Never expose the code hash for editing; challenges are system-managed.
    readonly_fields = (
        "id", "session", "channel", "destination", "code_hash",
        "attempts", "max_attempts", "expires_at", "consumed_at", "created_at",
    )

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OrderDraft)
class OrderDraftAdmin(admin.ModelAdmin):
    list_display = ("session", "service", "status", "updated_at")
    list_filter = ("status", "service")
    readonly_fields = ("id", "session", "created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "service", "currency", "amount", "status", "customer_ref", "created_at")
    list_filter = ("status", "service")
    # Amount/breakdown come from the pricing engine; never hand-edit money.
    readonly_fields = (
        "id", "session", "customer_ref", "service", "params",
        "currency", "amount", "breakdown", "created_at",
    )

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ref", "category", "reason", "status", "customer_ref", "created_at")
    list_filter = ("status", "category", "reason")
    # The attached transcript is an audit snapshot; never hand-edit it.
    readonly_fields = (
        "id", "ref", "session", "customer_ref", "subject", "category",
        "reason", "transcript", "status", "created_at",
    )

    @admin.display(description="Ref")
    def ref(self, obj):
        return obj.ref

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AgentEvent)
class AgentEventAdmin(admin.ModelAdmin):
    list_display = ("session", "seq", "step", "created_at")
    list_filter = ("step",)
    # Append-only: the audit log must never be edited or deleted from admin.
    readonly_fields = ("id", "session", "seq", "step", "payload", "created_at")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
