from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from audit.models import AuditLog
from banking.models import Account, Customer, Transaction
from monitoring import workflow
from monitoring.models import Alert, RuleConfig
from monitoring.screening import screen

pytestmark = pytest.mark.django_db
NOW = timezone.now()


def user(name, role):
    u = User.objects.create(username=name)
    u.groups.add(Group.objects.get(name=role))
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION='Token ' + Token.objects.create(user=u).key)
    return u, c


@pytest.fixture
def accounts():
    low = Customer.objects.create(customer_number='C1', full_name='Thandiwe Mokoena')
    high = Customer.objects.create(customer_number='C2', full_name='Shell Co', risk_rating='high')
    return {
        'cheque': Account.objects.create(account_number='1001', customer=low, type='cheque',
                                         opened_at=NOW - timedelta(days=400), last_activity_at=NOW - timedelta(days=1)),
        'business': Account.objects.create(account_number='2001', customer=high, type='business',
                                           opened_at=NOW - timedelta(days=400), last_activity_at=NOW - timedelta(days=1)),
        'dormant': Account.objects.create(account_number='3001', customer=low, type='savings', status='dormant',
                                          opened_at=NOW - timedelta(days=900), last_activity_at=NOW - timedelta(days=400)),
    }


@pytest.fixture
def ingest_client():
    return user('core-banking', 'ingest')[1]


def post(client, ext, account, amount, minutes_ago=0, **extra):
    body = {'external_id': ext, 'account_number': account, 'direction': 'debit', 'amount': str(amount),
            'channel': 'eft', 'occurred_at': (NOW - timedelta(minutes=minutes_ago)).isoformat(), **extra}
    return client.post('/api/transactions/', body, format='json')


def send(client, capture, *args, **kwargs):
    with capture(execute=True):
        return post(client, *args, **kwargs)


def rules_hit(ext):
    return sorted(Alert.objects.filter(transaction__external_id=ext).values_list('rule_code', flat=True))


# --- ingestion ---------------------------------------------------------------

def test_ingest_is_idempotent(accounts, ingest_client, django_capture_on_commit_callbacks):
    first = send(ingest_client, django_capture_on_commit_callbacks, 'TX-1', '1001', 120)
    again = send(ingest_client, django_capture_on_commit_callbacks, 'TX-1', '1001', 120)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()['status'] == 'duplicate'
    assert Transaction.objects.count() == 1


def test_batch_accepts_good_rows_and_reports_bad_ones(accounts, ingest_client, django_capture_on_commit_callbacks):
    rows = [
        {'external_id': 'B-1', 'account_number': '1001', 'direction': 'debit', 'amount': '10.00', 'channel': 'card',
         'occurred_at': NOW.isoformat()},
        {'external_id': 'B-2', 'account_number': '9999', 'direction': 'debit', 'amount': '10.00', 'channel': 'card',
         'occurred_at': NOW.isoformat()},
        {'external_id': 'B-3', 'account_number': '1001', 'direction': 'debit', 'amount': '-5', 'channel': 'card',
         'occurred_at': NOW.isoformat()},
    ]
    with django_capture_on_commit_callbacks(execute=True):
        r = ingest_client.post('/api/transactions/', rows, format='json')
    assert r.status_code == 207
    assert [a['external_id'] for a in r.json()['accepted']] == ['B-1']
    assert [e['index'] for e in r.json()['rejected']] == [1, 2]


def test_screening_runs_after_ingest(accounts, ingest_client, django_capture_on_commit_callbacks):
    send(ingest_client, django_capture_on_commit_callbacks, 'TX-BIG', '1001', 60000)
    txn = Transaction.objects.get(external_id='TX-BIG')
    assert txn.status == 'screened'
    assert rules_hit('TX-BIG') == ['LARGE_AMOUNT']
    assert txn.risk_score == 30


# --- rules -------------------------------------------------------------------

def test_large_amount_depends_on_account_type(accounts, ingest_client, django_capture_on_commit_callbacks):
    send(ingest_client, django_capture_on_commit_callbacks, 'L-1', '2001', 60000)   # business limit is 500k
    assert 'LARGE_AMOUNT' not in rules_hit('L-1')


def test_structuring(accounts, ingest_client, django_capture_on_commit_callbacks):
    for i, minutes in enumerate((300, 200, 100)):
        send(ingest_client, django_capture_on_commit_callbacks, 'S-%d' % i, '1001', 45000 + i, minutes,
             channel='cash', direction='credit')
    assert rules_hit('S-0') == []
    assert rules_hit('S-2') == ['STRUCTURING']
    assert '3 cash deposits' in Alert.objects.get(transaction__external_id='S-2').reason


def test_cash_over_threshold(accounts, ingest_client, django_capture_on_commit_callbacks):
    send(ingest_client, django_capture_on_commit_callbacks, 'C-1', '1001', 50000, channel='cash', direction='credit')
    assert rules_hit('C-1') == ['CASH_THRESHOLD', 'LARGE_AMOUNT']


def test_velocity(accounts, ingest_client, django_capture_on_commit_callbacks):
    for i in range(11):
        send(ingest_client, django_capture_on_commit_callbacks, 'V-%d' % i, '1001', 99, 50 - i * 4)
    assert rules_hit('V-9') == []
    assert rules_hit('V-10') == ['VELOCITY']


def test_duplicate_payment(accounts, ingest_client, django_capture_on_commit_callbacks):
    send(ingest_client, django_capture_on_commit_callbacks, 'D-1', '1001', 4500, 8, counterparty_account='4071234567')
    send(ingest_client, django_capture_on_commit_callbacks, 'D-2', '1001', 4500, 2, counterparty_account='4071234567')
    assert rules_hit('D-2') == ['DUPLICATE']


def test_dormant_account_and_high_risk_customer(accounts, ingest_client, django_capture_on_commit_callbacks):
    send(ingest_client, django_capture_on_commit_callbacks, 'Z-1', '3001', 9000)
    assert rules_hit('Z-1') == ['DORMANT_REACTIVATION']
    assert Account.objects.get(account_number='3001').status == 'active'

    send(ingest_client, django_capture_on_commit_callbacks, 'H-1', '2001', 25000)
    assert rules_hit('H-1') == ['HIGH_RISK_CUSTOMER']


def test_disabled_rule_and_tuned_threshold(accounts, ingest_client, django_capture_on_commit_callbacks):
    RuleConfig.objects.filter(code='LARGE_AMOUNT').update(params={'cheque': '10000'})
    send(ingest_client, django_capture_on_commit_callbacks, 'T-1', '1001', 12000)
    assert rules_hit('T-1') == ['LARGE_AMOUNT']

    RuleConfig.objects.filter(code='LARGE_AMOUNT').update(enabled=False)
    send(ingest_client, django_capture_on_commit_callbacks, 'T-2', '1001', 12000)
    assert rules_hit('T-2') == []


def test_screening_twice_does_not_duplicate_alerts(accounts, ingest_client, django_capture_on_commit_callbacks):
    send(ingest_client, django_capture_on_commit_callbacks, 'R-1', '1001', 60000)
    screen(Transaction.objects.get(external_id='R-1').pk)
    assert Alert.objects.filter(transaction__external_id='R-1').count() == 1


# --- alert workflow and access --------------------------------------------------

def make_alert(accounts, ingest_client, capture):
    send(ingest_client, capture, 'W-1', '1001', 60000)
    return Alert.objects.get(transaction__external_id='W-1')


def test_alert_workflow_and_supervisor_only_reporting(accounts, ingest_client, django_capture_on_commit_callbacks):
    alert = make_alert(accounts, ingest_client, django_capture_on_commit_callbacks)
    analyst, analyst_client = user('analyst1', 'analyst')
    _, supervisor_client = user('supervisor1', 'supervisor')

    r = analyst_client.post('/api/alerts/%d/transition/' % alert.id, {'status': 'investigating'}, format='json')
    assert r.status_code == 200 and r.json()['assigned_to'] == 'analyst1'

    r = analyst_client.post('/api/alerts/%d/transition/' % alert.id, {'status': 'escalated'}, format='json')
    assert r.status_code == 409 and 'note' in r.json()['detail']

    analyst_client.post('/api/alerts/%d/transition/' % alert.id,
                        {'status': 'escalated', 'note': 'customer could not explain source of funds'}, format='json')
    r = analyst_client.post('/api/alerts/%d/transition/' % alert.id,
                            {'status': 'closed_reported', 'note': 'report'}, format='json')
    assert r.status_code == 403

    r = supervisor_client.post('/api/alerts/%d/transition/' % alert.id,
                               {'status': 'closed_reported', 'note': 'reported to the FIC'}, format='json')
    assert r.status_code == 200
    assert len(r.json()['notes']) == 2

    actions = list(AuditLog.objects.filter(object_type='Alert', object_id=str(alert.id))
                   .order_by('id').values_list('action', flat=True))
    assert actions == ['alert.raised'] + ['alert.status_changed'] * 3


def test_invalid_transitions(accounts, ingest_client, django_capture_on_commit_callbacks):
    alert = make_alert(accounts, ingest_client, django_capture_on_commit_callbacks)
    analyst, _ = user('analyst1', 'analyst')
    with pytest.raises(workflow.WorkflowError):
        workflow.transition(alert, 'closed_reported', analyst, 'skip ahead')
    with pytest.raises(workflow.WorkflowError):
        workflow.transition(alert, 'nonsense', analyst)


def test_roles_are_enforced(accounts, ingest_client):
    _, analyst_client = user('analyst1', 'analyst')
    assert analyst_client.post('/api/transactions/', {}, format='json').status_code == 403
    assert ingest_client.get('/api/alerts/').status_code == 403
    assert analyst_client.get('/api/audit/').status_code == 403
    assert analyst_client.patch('/api/rules/VELOCITY/', {'enabled': False}, format='json').status_code == 403
    assert APIClient().get('/api/alerts/').status_code == 401


def test_rule_changes_are_validated_and_audited(accounts):
    _, supervisor_client = user('supervisor1', 'supervisor')
    bad = supervisor_client.patch('/api/rules/VELOCITY/', {'params': {'per_second': 5}}, format='json')
    assert bad.status_code == 400

    ok = supervisor_client.patch('/api/rules/VELOCITY/', {'params': {'count': 20}}, format='json')
    assert ok.status_code == 200
    entry = AuditLog.objects.get(action='rule.changed')
    assert entry.actor_label == 'supervisor1'
    assert entry.details['after']['params'] == {'count': 20}


def test_audit_log_is_append_only(accounts):
    entry = AuditLog.objects.create(actor_label='x', action='test', object_type='T', object_id='1')
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()


def test_health_endpoints(client):
    assert client.get('/healthz').status_code == 200
    assert client.get('/readyz').status_code == 200
