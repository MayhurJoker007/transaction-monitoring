from django.conf import settings
from django.db import models


class Severity(models.TextChoices):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'


class RuleConfig(models.Model):
    """Thresholds live in the database so compliance can tune them without a deploy. Every change is audited."""

    code = models.CharField(max_length=40, primary_key=True)
    enabled = models.BooleanField(default=True)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    params = models.JSONField(default=dict)
    description = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.code


class Alert(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open'
        INVESTIGATING = 'investigating'
        ESCALATED = 'escalated'
        CLOSED_FALSE_POSITIVE = 'closed_false_positive'
        CLOSED_REPORTED = 'closed_reported'

    transaction = models.ForeignKey('banking.Transaction', on_delete=models.PROTECT, related_name='alerts')
    rule_code = models.CharField(max_length=40)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        # screening can run twice for the same transaction (a retried task); it must not double the alerts
        constraints = [models.UniqueConstraint(fields=['transaction', 'rule_code'], name='one_alert_per_rule')]

    @property
    def is_closed(self):
        return self.status.startswith('closed')


class AlertNote(models.Model):
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
