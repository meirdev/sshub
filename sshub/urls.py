from django.contrib import admin
from django.urls import path

from core import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ssh/<int:host_id>/", views.ssh_terminal, name="ssh_terminal"),
    path(
        "snippet-exec/<uuid:batch_id>/",
        views.snippet_batch_results,
        name="snippet_batch_results",
    ),
]
