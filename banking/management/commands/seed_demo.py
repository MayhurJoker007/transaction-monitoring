"""Demo users, customers and accounts. Prints API tokens for each role.

    python manage.py seed_demo
"""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.authtoken.models import Token

from banking.models import Account, Customer

CUSTOMERS = [
    ('C1001', 'Thandiwe Mokoena', 'low', [('620010001', 'cheque'), ('620010002', 'savings')]),
    ('C1002', 'Pieter van der Merwe', 'medium', [('620010101', 'cheque')]),
    ('C1003', 'Ubuntu Liquor Distributors (Pty) Ltd', 'high', [('620020001', 'business')]),
    ('C1004', 'Sipho Ndlovu', 'low', [('620010301', 'savings')]),
]


class Command(BaseCommand):
    help = 'Creates demo users, customers and accounts'

    def handle(self, *args, **options):
        now = timezone.now()
        for number, name, risk, accounts in CUSTOMERS:
            c, _ = Customer.objects.get_or_create(customer_number=number,
                                                  defaults={'full_name': name, 'risk_rating': risk})
            for acc, kind in accounts:
                Account.objects.get_or_create(account_number=acc, defaults={
                    'customer': c, 'type': kind, 'opened_at': now - timedelta(days=900),
                    'last_activity_at': now - timedelta(days=2)})
        # one account that hasn't been used for a year
        Account.objects.filter(account_number='620010301').update(
            status=Account.Status.DORMANT, last_activity_at=now - timedelta(days=365))

        for username, role in (('core-banking', 'ingest'), ('analyst1', 'analyst'), ('supervisor1', 'supervisor')):
            user, _ = User.objects.get_or_create(username=username)
            user.groups.add(Group.objects.get(name=role))
            token, _ = Token.objects.get_or_create(user=user)
            self.stdout.write('%-12s %-11s token %s' % (username, role, token.key))
