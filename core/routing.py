from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/ssh/<int:host_id>/", consumers.SSHConsumer.as_asgi()),
    path(
        "ws/snippet-exec/<uuid:batch_id>/", consumers.SnippetExecutionConsumer.as_asgi()
    ),
]
