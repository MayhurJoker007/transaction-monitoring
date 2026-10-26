"""Detection rules.

Each rule looks at one transaction plus what it needs of the account's recent history and either returns a reason
string (a hit) or None. Thresholds come from RuleConfig.params, falling back to the defaults below.

These are illustrative patterns of the kind a bank's monitoring team tunes; the numbers are defaults to be set by
compliance, not legal thresholds.
"""
from datetime import timedelta
from decimal import Decimal

from banking.models import Transaction

RULES = {}


def rule(code, severity, defaults, description):
    def register(fn):
        RULES[code] = {'fn': fn, 'severity': severity, 'defaults': defaults, 'description': description}
        return fn
    return register


def _recent(txn, window, **filters):
    return Transaction.objects.filter(
        account=txn.account, occurred_at__gt=txn.occurred_at - window, occurred_at__lte=txn.occurred_at, **filters,
    ).exclude(pk=txn.pk)


def _money(v):
    return 'R{:,.2f}'.format(Decimal(v)).replace(',', ' ')


@rule('LARGE_AMOUNT', 'medium',
      {'cheque': '50000', 'savings': '100000', 'business': '500000'},
      'Single transaction above the limit for the account type')
def large_amount(txn, p):
    limit = Decimal(p.get(txn.account.type, p.get('cheque')))
    if txn.amount >= limit:
        return '%s is at or above the %s limit of %s' % (_money(txn.amount), txn.account.type, _money(limit))


@rule('CASH_THRESHOLD', 'high', {'threshold': '49999.99'},
      'Cash deposit above the cash reporting threshold')
def cash_threshold(txn, p):
    if txn.channel == 'cash' and txn.direction == 'credit' and txn.amount > Decimal(p['threshold']):
        return 'cash deposit of %s exceeds %s' % (_money(txn.amount), _money(p['threshold']))


@rule('STRUCTURING', 'high', {'threshold': '49999.99', 'band': '0.8', 'count': 3, 'hours': 24},
      'Several cash deposits just under the threshold in a short time')
def structuring(txn, p):
    if txn.channel != 'cash' or txn.direction != 'credit':
        return None
    threshold, low = Decimal(p['threshold']), Decimal(p['threshold']) * Decimal(p['band'])
    if not (low <= txn.amount <= threshold):
        return None
    earlier = _recent(txn, timedelta(hours=p['hours']), channel='cash', direction='credit',
                      amount__gte=low, amount__lte=threshold)
    if earlier.count() + 1 >= p['count']:
        total = sum((t.amount for t in earlier), txn.amount)
        return '%d cash deposits between %s and %s in %dh, %s in total' % (
            earlier.count() + 1, _money(low), _money(threshold), p['hours'], _money(total))


@rule('VELOCITY', 'medium', {'count': 10, 'minutes': 60},
      'Unusually many debits in a short window')
def velocity(txn, p):
    if txn.direction != 'debit':
        return None
    n = _recent(txn, timedelta(minutes=p['minutes']), direction='debit').count() + 1
    if n > p['count']:
        return '%d debits within %d minutes' % (n, p['minutes'])


@rule('DUPLICATE', 'low', {'minutes': 10},
      'Same amount to the same counterparty again within minutes')
def duplicate(txn, p):
    if not txn.counterparty_account:
        return None
    twin = _recent(txn, timedelta(minutes=p['minutes']), direction=txn.direction, amount=txn.amount,
                   counterparty_account=txn.counterparty_account).first()
    if twin:
        return 'same %s to %s as %s, %d min earlier' % (
            _money(txn.amount), txn.counterparty_account, twin.external_id,
            (txn.occurred_at - twin.occurred_at).total_seconds() // 60)


@rule('DORMANT_REACTIVATION', 'medium', {'min_amount': '5000'},
      'Large debit from an account that had been dormant')
def dormant_reactivation(txn, p):
    if txn.account_was_dormant and txn.direction == 'debit' and txn.amount >= Decimal(p['min_amount']):
        return 'debit of %s on an account that was dormant' % _money(txn.amount)


@rule('HIGH_RISK_CUSTOMER', 'medium', {'min_amount': '20000'},
      'Large transaction by a customer rated high risk')
def high_risk_customer(txn, p):
    if txn.account.customer.risk_rating == 'high' and txn.amount >= Decimal(p['min_amount']):
        return '%s by a high-risk customer' % _money(txn.amount)


SEVERITY_POINTS = {'low': 10, 'medium': 30, 'high': 60}
