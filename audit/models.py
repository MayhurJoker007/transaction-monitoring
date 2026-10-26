from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Who did what, when. Append-only: rows can't be changed or deleted through the ORM."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    actor_label = models.CharField(max_length=150)      # kept even if the user is later renamed
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=64, db_index=True)
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ['-at', '-id']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('audit entries are append-only')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('audit entries are append-only')

    def __str__(self):
        return '%s %s %s:%s' % (self.at, self.actor_label, self.object_type, self.object_id)
