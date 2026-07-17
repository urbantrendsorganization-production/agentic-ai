from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("whoami/", views.whoami, name="whoami"),
    path("sessions/", views.create_session, name="create-session"),
    path("sessions/<uuid:session_id>/messages/", views.post_message, name="post-message"),
    path("sessions/<uuid:session_id>/order/form/", views.order_form, name="order-form"),
]
