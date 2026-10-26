"""Posts a realistic mix of transactions through the real ingestion path, with a few suspicious patterns
mixed in so the rules have something to find.

    python manage.py simulate --count 300
"""
import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from banking.models import Account
from banking.services import ingest


class Command(BaseCommand):
    help = 'Generates demo transactions, including some suspicious ones'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=200)
        parser.add_argument('--seed', type=int, default=11)

    def handle(self, *args, count, seed, **options):
        rng = random.Random(seed)
        actor = User.objects.get(username='core-banking')
        accounts = list(Account.objects.exclude(status__in=[Account.Status.CLOSED, Account.Status.DORMANT]))
        now = timezone.now()

        def post(account, amount, channel='eft', direction='debit', when=None, counterparty='', name=''):
            ingest({
                'external_id': 'SIM-' + uuid.uuid4().hex[:12], 'account_number': account.account_number,
                'direction': direction, 'amount': Decimal(amount).quantize(Decimal('0.01')), 'channel': channel,
                'counterparty_account': counterparty, 'counterparty_name': name,
                'occurred_at': when or now - timedelta(minutes=rng.randint(0, 600)),
            }, actor)

        for _ in range(count):
            acc = rng.choice(accounts)
            post(acc, rng.choice([rng.uniform(50, 2500), rng.uniform(2500, 15000)]),
                 channel=rng.choice(['eft', 'card', 'card', 'atm']),
                 direction=rng.choice(['debit', 'debit', 'credit']),
                 counterparty='%010d' % rng.randint(1, 10**9))

        business = Account.objects.get(account_number='620020001')
        for minutes in (300, 200, 90):                                                # structuring
            post(business, rng.uniform(42000, 49000), channel='cash', direction='credit',
                 when=now - timedelta(minutes=minutes))
        post(Account.objects.get(account_number='620010101'), 75000)                 # large amount
        payer = Account.objects.get(account_number='620010001')                       # paid twice
        post(payer, 4500, counterparty='4071234567', name='Lucky Star Furniture', when=now - timedelta(minutes=7))
        post(payer, 4500, counterparty='4071234567', name='Lucky Star Furniture', when=now - timedelta(minutes=3))
        post(Account.objects.get(account_number='620010301'), 18000, when=now)       # dormant account wakes up
        self.stdout.write('posted %d transactions' % (count + 7))
