from django.contrib import admin

from .models import Alert, RuleConfig


@admin.register(RuleConfig)
class RuleConfigAdmin(admin.ModelAdmin):
    list_display = ['code', 'enabled', 'severity', 'params', 'updated_at']


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['id', 'rule_code', 'severity', 'status', 'assigned_to', 'created_at']
    list_filter = ['status', 'severity', 'rule_code']
    raw_id_fields = ['transaction']
