from celery import shared_task
from django.db import OperationalError

from .screening import screen


@shared_task(bind=True, autoretry_for=(OperationalError,), retry_backoff=True, retry_backoff_max=300, max_retries=8)
def screen_transaction(self, transaction_id):
    """Runs on the screening queue, in its own worker deployment, so a backlog of screening never slows ingestion."""
    hits = screen(transaction_id)
    return [code for code, _, _ in hits]
