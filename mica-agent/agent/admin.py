from django.contrib import admin

from .models import AgentEvent, LoginChallenge, Message, Session


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
