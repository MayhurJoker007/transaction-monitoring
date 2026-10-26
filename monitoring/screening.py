import logging

from django.db import IntegrityError, transaction

from audit.service import record
from banking.models import Transaction

from .models import Alert, RuleConfig
from .rules import RULES, SEVERITY_POINTS

log = logging.getLogger(__name__)


def ensure_rule_configs():
    """Creates a config row for any rule that doesn't have one yet, with the rule's defaults."""
    for code, r in RULES.items():
        RuleConfig.objects.get_or_create(code=code, defaults={
            'severity': r['severity'], 'params': r['defaults'], 'description': r['description']})


def screen(transaction_id):
    """Runs every enabled rule. Safe to run more than once for the same transaction."""
    txn = Transaction.objects.select_related('account__customer').get(pk=transaction_id)
    configs = {c.code: c for c in RuleConfig.objects.filter(enabled=True)}

    hits = []
    for code, r in RULES.items():
        cfg = configs.get(code)
        if cfg is None:
            continue
        params = {**r['defaults'], **cfg.params}
        try:
            reason = r['fn'](txn, params)
        except Exception:
            # one broken rule (a bad parameter typed in by someone) must not stop the others
            log.exception('rule %s failed on %s', code, txn.external_id)
            continue
        if reason:
            hits.append((code, cfg.severity, reason))

    with transaction.atomic():
        for code, severity, reason in hits:
            try:
                with transaction.atomic():
                    alert = Alert.objects.create(transaction=txn, rule_code=code, severity=severity, reason=reason)
                record(None, 'alert.raised', alert, rule=code, severity=severity, transaction=txn.external_id)
            except IntegrityError:
                pass  # already raised by an earlier run of this screening
        txn.risk_score = min(100, sum(SEVERITY_POINTS[s] for _, s, _ in hits))
        txn.status = Transaction.Status.SCREENED
        txn.save(update_fields=['risk_score', 'status'])
    return hits
