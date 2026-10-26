import uuid

from django.db import models


class Customer(models.Model):
    class Risk(models.TextChoices):
        LOW = 'low'
        MEDIUM = 'medium'
        HIGH = 'high'

    customer_number = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=200)
    risk_rating = models.CharField(max_length=10, choices=Risk.choices, default=Risk.LOW)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return '%s %s' % (self.customer_number, self.full_name)


class Account(models.Model):
    class Type(models.TextChoices):
        CHEQUE = 'cheque'
        SAVINGS = 'savings'
        BUSINESS = 'business'

    class Status(models.TextChoices):
        ACTIVE = 'active'
        DORMANT = 'dormant'
        CLOSED = 'closed'

    account_number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='accounts')
    type = models.CharField(max_length=10, choices=Type.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    currency = models.CharField(max_length=3, default='ZAR')
    opened_at = models.DateTimeField()
    last_activity_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.account_number


class Transaction(models.Model):
    class Direction(models.TextChoices):
        DEBIT = 'debit'
        CREDIT = 'credit'

    class Channel(models.TextChoices):
        EFT = 'eft'
        CARD = 'card'
        CASH = 'cash'
        ATM = 'atm'
        INTERNAL = 'internal'

    class Status(models.TextChoices):
        RECEIVED = 'received'
        SCREENED = 'screened'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The core banking system's id. Unique, so a re-sent batch can't create duplicates.
    external_id = models.CharField(max_length=64, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transactions')
    direction = models.CharField(max_length=6, choices=Direction.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default='ZAR')
    channel = models.CharField(max_length=10, choices=Channel.choices)
    counterparty_account = models.CharField(max_length=34, blank=True)
    counterparty_name = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=200, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED)
    risk_score = models.PositiveSmallIntegerField(default=0)
    # what the account looked like when this arrived; screening needs it, and it changes once we record activity
    account_was_dormant = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['account', 'occurred_at'])]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='amount_positive')]

    def __str__(self):
        return '%s %s %s' % (self.external_id, self.direction, self.amount)
