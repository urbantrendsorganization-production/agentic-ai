from django.apps import AppConfig


class AgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agent"

    def ready(self):
        # Import tool modules so they register themselves on startup.
        from . import tools  # noqa: F401
