from django.contrib import admin
from django.http import JsonResponse
from django.db import connection
from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from banking.api import AccountTransactionsView, IngestView
from monitoring.api import AlertAssign, AlertDetail, AlertList, AlertTransition, AuditList, RuleList, RuleUpdate


def health(request):
    return JsonResponse({'status': 'ok'})


def ready(request):
    # Kubernetes readiness: only take traffic once the database answers
    with connection.cursor() as c:
        c.execute('select 1')
    return JsonResponse({'status': 'ready'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz', health),
    path('readyz', ready),
    path('api/token/', obtain_auth_token),
    path('api/transactions/', IngestView.as_view()),
    path('api/accounts/<str:account_number>/transactions/', AccountTransactionsView.as_view()),
    path('api/alerts/', AlertList.as_view()),
    path('api/alerts/<int:pk>/', AlertDetail.as_view()),
    path('api/alerts/<int:pk>/transition/', AlertTransition.as_view()),
    path('api/alerts/<int:pk>/assign/', AlertAssign.as_view()),
    path('api/rules/', RuleList.as_view()),
    path('api/rules/<str:code>/', RuleUpdate.as_view()),
    path('api/audit/', AuditList.as_view()),
]
