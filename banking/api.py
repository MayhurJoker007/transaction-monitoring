from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.permissions import role_required

from .models import Account, Transaction
from .services import IngestError, ingest


class TransactionIn(serializers.Serializer):
    external_id = serializers.CharField(max_length=64)
    account_number = serializers.CharField(max_length=20)
    direction = serializers.ChoiceField(Transaction.Direction.choices)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.CharField(max_length=3, required=False)
    channel = serializers.ChoiceField(Transaction.Channel.choices)
    counterparty_account = serializers.CharField(max_length=34, required=False, allow_blank=True)
    counterparty_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField()


class TransactionOut(serializers.ModelSerializer):
    account_number = serializers.CharField(source='account.account_number')
    alerts = serializers.SlugRelatedField(many=True, read_only=True, slug_field='rule_code')

    class Meta:
        model = Transaction
        fields = ['id', 'external_id', 'account_number', 'direction', 'amount', 'currency', 'channel',
                  'counterparty_account', 'counterparty_name', 'description', 'occurred_at', 'received_at',
                  'status', 'risk_score', 'alerts']


class IngestView(APIView):
    """Core banking (or its integration layer) posts transactions here, one at a time or up to 500 per batch."""
    permission_classes = [role_required('ingest')]

    def post(self, request):
        many = isinstance(request.data, list)
        items = request.data if many else [request.data]
        if len(items) > 500:
            return Response({'detail': 'at most 500 transactions per request'}, status=413)

        results, errors = [], []
        for i, item in enumerate(items):
            s = TransactionIn(data=item)
            if not s.is_valid():
                errors.append({'index': i, 'errors': s.errors})
                continue
            try:
                txn, created = ingest(s.validated_data, request.user)
                results.append({'index': i, 'id': str(txn.id), 'external_id': txn.external_id,
                                'status': 'created' if created else 'duplicate'})
            except IngestError as e:
                errors.append({'index': i, 'errors': {'detail': str(e)}})

        if not many:
            if errors:
                return Response(errors[0]['errors'], status=400)
            return Response(results[0], status=201 if results[0]['status'] == 'created' else 200)
        # a batch is accepted line by line: one bad row doesn't block 499 good ones
        return Response({'accepted': results, 'rejected': errors},
                        status=status.HTTP_207_MULTI_STATUS if errors else 201)


class AccountTransactionsView(ListAPIView):
    permission_classes = [role_required('analyst', 'supervisor')]
    serializer_class = TransactionOut

    def get_queryset(self):
        account = Account.objects.get(account_number=self.kwargs['account_number'])
        return (Transaction.objects.filter(account=account).select_related('account')
                .prefetch_related('alerts').order_by('-occurred_at'))

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except Account.DoesNotExist:
            return Response({'detail': 'account not found'}, status=404)
