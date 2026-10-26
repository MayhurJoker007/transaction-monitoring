from django.contrib import admin

from .models import Account, Customer, Transaction


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['customer_number', 'full_name', 'risk_rating']
    search_fields = ['customer_number', 'full_name']


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['account_number', 'customer', 'type', 'status', 'last_activity_at']
    search_fields = ['account_number']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['external_id', 'account', 'direction', 'amount', 'channel', 'occurred_at', 'risk_score']
    list_filter = ['channel', 'direction', 'status']
    search_fields = ['external_id']
