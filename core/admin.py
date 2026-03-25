import uuid

from django import forms
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect, render
from django.utils.html import format_html, format_html_join

from .models import ClientKey, CustomLogEntry, Host, HostTag, Snippet, SnippetExecution
from .widgets import CodeMirrorWidget


class ClientKeyForm(forms.ModelForm):
    passphrase = forms.CharField(widget=forms.PasswordInput, required=False)

    class Meta:
        model = ClientKey
        fields = "__all__"


@admin.register(ClientKey)
class ClientKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "public_key", "passphrase")
    search_fields = ("name",)


class HostForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False)

    class Meta:
        model = Host
        fields = "__all__"


@admin.register(Host)
class HostAdmin(admin.ModelAdmin):
    list_display = (
        "display_icon",
        "name",
        "host",
        "port",
        "username",
        "proxy_jump",
        "display_tags",
        "connect_link",
    )
    list_display_links = ("name",)
    list_filter = ("tags",)
    search_fields = ("name", "host", "username")
    filter_horizontal = ("client_keys", "tags")
    form = HostForm

    class Media:
        js = ("core/js/ssh_terminal.js",)

    def display_icon(self, obj):
        return format_html(
            '<img src="/static/core/images/{}.svg" width="20" height="20" alt="{}">',
            obj.icon,
            obj.get_icon_display(),
        )

    display_icon.short_description = ""

    def display_tags(self, obj):
        tags = obj.tags.all()
        if not tags:
            return ""
        return format_html_join(
            " ",
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:10px;font-size:small;display:inline-block">{}</span>',
            ((tag.color, tag.name) for tag in tags),
        )

    display_tags.short_description = "Tags"

    def connect_link(self, obj):
        return format_html(
            '<a href="#" class="ssh-connect" data-host-id="{}" data-host-name="{}">Connect</a>',
            obj.pk,
            obj.name,
        )

    connect_link.short_description = "SSH"


@admin.register(HostTag)
class HostTagAdmin(admin.ModelAdmin):
    list_display = ("name", "color")
    search_fields = ("name",)


class SnippetForm(forms.ModelForm):
    class Meta:
        model = Snippet
        fields = "__all__"
        widgets = {
            "script": CodeMirrorWidget(attrs={"class": "codemirror"}),
        }


class RunOnForm(forms.Form):
    hosts = forms.ModelMultipleChoiceField(
        queryset=Host.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    tags = forms.ModelMultipleChoiceField(
        queryset=HostTag.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )


@admin.register(Snippet)
class SnippetAdmin(admin.ModelAdmin):
    list_display = ("name", "updated_at")
    search_fields = ("name",)
    form = SnippetForm
    actions = ["run_on"]

    @admin.action(description="Run on hosts...")
    def run_on(self, request, queryset):
        if "apply" in request.POST:
            run_form = RunOnForm(request.POST)
            if run_form.is_valid():
                hosts = set(run_form.cleaned_data["hosts"])
                for tag in run_form.cleaned_data["tags"]:
                    hosts.update(tag.host_set.all())

                if not hosts:
                    self.message_user(request, "No hosts selected.", level="error")
                    return

                batch_id = uuid.uuid4()
                snippet_ct = ContentType.objects.get_for_model(Snippet)
                for snippet in queryset:
                    for host in hosts:
                        SnippetExecution.objects.create(
                            snippet=snippet,
                            host=host,
                            batch_id=batch_id,
                            created_by=request.user,
                        )
                    CustomLogEntry.objects.create(
                        content_type=snippet_ct,
                        object_pk=str(snippet.pk),
                        object_id=snippet.pk,
                        object_repr=str(snippet),
                        action=CustomLogEntry.Action.SNIPPET_RUN,
                        actor=request.user,
                        additional_data={"hosts": [str(h) for h in hosts]},
                    )

                return redirect("snippet_batch_results", batch_id=batch_id)

        run_form = RunOnForm()
        return render(
            request,
            "admin/core/snippet/run_on.html",
            {
                "snippets": queryset,
                "run_form": run_form,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
                "opts": self.model._meta,
                "title": "Run snippets on hosts",
            },
        )


@admin.register(SnippetExecution)
class SnippetExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "snippet",
        "host",
        "status",
        "exit_code",
        "started_at",
        "finished_at",
        "created_by",
    )
    list_filter = ("status", "snippet", "host")
    readonly_fields = (
        "snippet",
        "host",
        "status",
        "live_output",
        "exit_code",
        "started_at",
        "finished_at",
        "created_by",
        "batch_id",
    )
    exclude = ("output",)

    def has_add_permission(self, request):
        return False

    def live_output(self, obj):
        from django.template.loader import render_to_string

        return render_to_string(
            "core/widgets/live_output.html",
            {"execution_id": obj.pk, "batch_id": obj.batch_id, "output": obj.output},
        )

    live_output.short_description = "Output"
