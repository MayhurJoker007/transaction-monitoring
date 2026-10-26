from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _setup(sender, **kwargs):
    from django.contrib.auth.models import Group

    from .screening import ensure_rule_configs
    for role in ('ingest', 'analyst', 'supervisor'):
        Group.objects.get_or_create(name=role)
    ensure_rule_configs()


class MonitoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'monitoring'

    def ready(self):
        # roles and rule rows exist as soon as the database is migrated, in every environment
        post_migrate.connect(_setup, sender=self)
