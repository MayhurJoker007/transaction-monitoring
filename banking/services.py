"""Transaction ingestion. The only job here is to store the transaction safely and hand it to screening;
the rules live in the monitoring app, which is deployed as a separate worker."""
from datetime import timedelta

from django.db import IntegrityError, transaction

from audit.service import record

from .models import Account, Transaction

DORMANT_AFTER = timedelta(days=180)


class IngestError(ValueError):
    pass


def ingest(data, actor):
    """Returns (transaction, created). Re-sending the same external_id returns the original."""
    existing = Transaction.objects.filter(external_id=data['external_id']).first()
    if existing:
        return existing, False

    try:
        account = Account.objects.get(account_number=data['account_number'])
    except Account.DoesNotExist:
        raise IngestError('unknown account %s' % data['account_number'])
    if account.status == Account.Status.CLOSED:
        raise IngestError('account %s is closed' % account.account_number)
    if data.get('currency', account.currency) != account.currency:
        raise IngestError('currency %s does not match account currency %s' % (data['currency'], account.currency))

    occurred = data['occurred_at']
    was_dormant = account.status == Account.Status.DORMANT or (
        account.last_activity_at is not None and occurred - account.last_activity_at > DORMANT_AFTER)

    try:
        with transaction.atomic():
            txn = Transaction.objects.create(
                external_id=data['external_id'], account=account, direction=data['direction'],
                amount=data['amount'], currency=account.currency, channel=data['channel'],
                counterparty_account=data.get('counterparty_account', ''),
                counterparty_name=data.get('counterparty_name', ''),
                description=data.get('description', ''), occurred_at=occurred, account_was_dormant=was_dormant)
            if account.last_activity_at is None or occurred > account.last_activity_at:
                account.last_activity_at = occurred
                if account.status == Account.Status.DORMANT:
                    account.status = Account.Status.ACTIVE
                account.save(update_fields=['last_activity_at', 'status'])
            record(actor, 'transaction.ingested', txn, external_id=txn.external_id, amount=str(txn.amount))

            # Only queue screening once the row is committed, or the worker might look before it exists
            from monitoring.tasks import screen_transaction
            transaction.on_commit(lambda: screen_transaction.delay(str(txn.id)))
    except IntegrityError:
        # same external_id arrived twice at the same moment; the other request stored it
        return Transaction.objects.get(external_id=data['external_id']), False
    return txn, True
