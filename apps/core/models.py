import uuid

from django.db import models


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=100)
    key = models.CharField(max_length=100)
    payload = models.JSONField()
    headers = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=models.Q(published_at__isnull=True),
                name="outbox_unpublished",
            )
        ]

    def __str__(self) -> str:
        return f"{self.topic}:{self.payload.get('type')}:{self.id}"
