from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_list_or_404, get_object_or_404, render

from .models import Host, SnippetExecution


@staff_member_required
def ssh_terminal(request, host_id):
    host = get_object_or_404(Host, pk=host_id)
    return render(request, "core/ssh_terminal.html", {"host": host})


@staff_member_required
def snippet_batch_results(request, batch_id):
    executions = get_list_or_404(
        SnippetExecution.objects.select_related("snippet", "host"),
        batch_id=batch_id,
    )
    snippet_name = executions[0].snippet.name
    return render(
        request,
        "core/snippet_batch_results.html",
        {
            "batch_id": batch_id,
            "executions": executions,
            "snippet_name": snippet_name,
        },
    )
