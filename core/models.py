import validators
from auditlog.models import AbstractLogEntry
from auditlog.registry import auditlog
from colorfield.fields import ColorField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .fields import EncryptedCharField


def validate_host(value: str) -> None:
    if not (
        validators.hostname(value) or validators.ipv4(value) or validators.ipv6(value)
    ):
        raise ValidationError(
            "%(value)s is not a valid hostname or IP address.",
            params={"value": value},
        )


class ClientKey(models.Model):
    name = models.CharField(max_length=255)
    public_key = models.TextField()
    passphrase = EncryptedCharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.name}"


class Host(models.Model):
    class Icon(models.TextChoices):
        LINUX = "linux", "Linux"
        UBUNTU = "ubuntu", "Ubuntu"
        DEBIAN = "debian", "Debian"
        ALPINE = "alpine", "Alpine"
        REDHAT = "redhat", "Red Hat"
        WINDOWS = "windows", "Windows"

    name = models.CharField(max_length=255, unique=True)
    host = models.CharField(max_length=255, validators=[validate_host])
    port = models.PositiveSmallIntegerField(
        default=22,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    username = models.CharField(max_length=255, blank=True)
    password = EncryptedCharField(max_length=255, blank=True)
    client_keys = models.ManyToManyField("ClientKey", blank=True)
    proxy_jump = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="proxy_jump_hosts",
    )
    tags = models.ManyToManyField("HostTag", blank=True)
    icon = models.CharField(max_length=20, choices=Icon, default=Icon.LINUX)

    @property
    def route(self) -> list["Host"]:
        """Return the proxy_jump chain in connect order (outermost jump first, self last).

        Raises ValueError on circular chains.
        """
        hosts: list[Host] = [self]
        visited_ids = {self.pk}

        current: Host = self
        while current.proxy_jump_id is not None:
            current = current.proxy_jump  # ty:ignore[invalid-assignment]
            if current.pk in visited_ids:
                raise ValueError("Circular proxy_jump detected")

            visited_ids.add(current.pk)
            hosts.append(current)

        hosts.reverse()
        return hosts

    def clean(self):
        super().clean()

        if self.proxy_jump_id is None:
            return

        try:
            self.route
        except ValueError:
            raise ValidationError({"proxy_jump": "Circular proxy jump chain detected."})

    def __str__(self) -> str:
        return f"{self.name}"


class HostTag(models.Model):
    name = models.CharField(max_length=255, unique=True)
    color = ColorField(default="#aaaaaa")

    def __str__(self) -> str:
        return f"{self.name}"


class CustomLogEntry(AbstractLogEntry):
    class Action(AbstractLogEntry.Action):
        CONNECT = 4
        DISCONNECT = 5
        SNIPPET_RUN = 6

        choices = AbstractLogEntry.Action.choices + (
            (CONNECT, _("connect")),
            (DISCONNECT, _("disconnect")),
            (SNIPPET_RUN, _("snippet run")),
        )

    action = models.PositiveSmallIntegerField(
        choices=Action.choices, verbose_name=_("action"), db_index=True
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = _("log entry")
        verbose_name_plural = _("log entries")


class Snippet(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    script = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name}"


class SnippetExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        RUNNING = "running", _("Running")
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")

    snippet = models.ForeignKey(
        Snippet, on_delete=models.CASCADE, related_name="executions"
    )
    host = models.ForeignKey(Host, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=Status, default=Status.PENDING)
    output = models.TextField(blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    batch_id = models.UUIDField(db_index=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.snippet.name} on {self.host} ({self.status})"


auditlog.register(ClientKey)
auditlog.register(Host)
auditlog.register(HostTag)
auditlog.register(Snippet)
