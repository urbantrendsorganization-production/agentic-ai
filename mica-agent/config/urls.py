from django.contrib import admin
from django.urls import include, path

from agent import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("agent.urls")),
    path("", views.widget_demo, name="widget-demo"),
]
