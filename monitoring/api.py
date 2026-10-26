from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog
from audit.permissions import role_required
from audit.service import record

from . import workflow
from .models import Alert, AlertNote, RuleConfig
from .rules import RULES

analysts = role_required('analyst', 'supervisor')
supervisors = role_required('supervisor')


class NoteOut(serializers.ModelSerializer):
    author = serializers.CharField(source='author.username')

    class Meta:
        model = AlertNote
        fields = ['author', 'text', 'created_at']


class AlertOut(serializers.ModelSerializer):
    transaction = serializers.CharField(source='transaction.external_id')
    account_number = serializers.CharField(source='transaction.account.account_number')
    amount = serializers.DecimalField(source='transaction.amount', max_digits=14, decimal_places=2)
    assigned_to = serializers.CharField(source='assigned_to.username', default=None)
    notes = NoteOut(many=True, read_only=True)

    class Meta:
        model = Alert
        fields = ['id', 'rule_code', 'severity', 'reason', 'status', 'transaction', 'account_number', 'amount',
                  'assigned_to', 'created_at', 'updated_at', 'notes']


class AlertList(ListAPIView):
    permission_classes = [analysts]
    serializer_class = AlertOut

    def get_queryset(self):
        q = Alert.objects.select_related('transaction__account', 'assigned_to').prefetch_related('notes__author')
        for field in ('status', 'severity', 'rule_code'):
            if value := self.request.query_params.get(field):
                q = q.filter(**{field: value})
        if self.request.query_params.get('mine'):
            q = q.filter(assigned_to=self.request.user)
        return q


class AlertDetail(RetrieveAPIView):
    permission_classes = [analysts]
    serializer_class = AlertOut
    queryset = Alert.objects.select_related('transaction__account', 'assigned_to').prefetch_related('notes__author')


class AlertTransition(APIView):
    permission_classes = [analysts]

    def post(self, request, pk):
        alert = get_object_or_404(Alert, pk=pk)
        try:
            workflow.transition(alert, request.data.get('status', ''), request.user, request.data.get('note', ''))
        except ValueError as e:
            return Response({'detail': str(e)}, status=409)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=403)
        return Response(AlertOut(alert).data)


class AlertAssign(APIView):
    permission_classes = [supervisors]

    def post(self, request, pk):
        alert = get_object_or_404(Alert, pk=pk)
        assignee = get_object_or_404(get_user_model(), username=request.data.get('username'))
        try:
            workflow.assign(alert, assignee, request.user)
        except workflow.WorkflowError as e:
            return Response({'detail': str(e)}, status=409)
        return Response(AlertOut(alert).data)


class RuleOut(serializers.ModelSerializer):
    class Meta:
        model = RuleConfig
        fields = ['code', 'enabled', 'severity', 'params', 'description', 'updated_at']
        read_only_fields = ['code', 'description', 'updated_at']

    def validate_params(self, value):
        unknown = set(value) - set(RULES[self.instance.code]['defaults'])
        if unknown:
            raise serializers.ValidationError('unknown parameters: %s' % ', '.join(sorted(unknown)))
        return value


class RuleList(ListAPIView):
    permission_classes = [analysts]
    serializer_class = RuleOut
    queryset = RuleConfig.objects.order_by('code')


class RuleUpdate(APIView):
    permission_classes = [supervisors]

    def patch(self, request, code):
        rule = get_object_or_404(RuleConfig, code=code)
        before = RuleOut(rule).data
        s = RuleOut(rule, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        record(request.user, 'rule.changed', rule, before={k: before[k] for k in ('enabled', 'severity', 'params')},
               after={k: s.data[k] for k in ('enabled', 'severity', 'params')})
        return Response(s.data)


class AuditOut(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['at', 'actor_label', 'action', 'object_type', 'object_id', 'details']


class AuditList(ListAPIView):
    permission_classes = [supervisors]
    serializer_class = AuditOut

    def get_queryset(self):
        q = AuditLog.objects.all()
        for field in ('action', 'object_type', 'object_id'):
            if value := self.request.query_params.get(field):
                q = q.filter(**{field: value})
        return q
