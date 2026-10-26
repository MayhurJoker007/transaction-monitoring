"""Alert case management: who can move an alert where."""
from django.db import transaction

from audit.service import record

from .models import Alert, AlertNote

S = Alert.Status

TRANSITIONS = {
    S.OPEN: {S.INVESTIGATING, S.CLOSED_FALSE_POSITIVE},
    S.INVESTIGATING: {S.ESCALATED, S.CLOSED_FALSE_POSITIVE},
    S.ESCALATED: {S.CLOSED_REPORTED, S.CLOSED_FALSE_POSITIVE, S.INVESTIGATING},
}
# Analysts investigate and escalate; deciding to report is a supervisor call
SUPERVISOR_ONLY = {S.CLOSED_REPORTED}
NOTE_REQUIRED = {S.CLOSED_FALSE_POSITIVE, S.CLOSED_REPORTED, S.ESCALATED}


class WorkflowError(ValueError):
    pass


def is_supervisor(user):
    return user.groups.filter(name='supervisor').exists() or user.is_superuser


def transition(alert, to, user, note=''):
    if to not in S.values:
        raise WorkflowError('unknown status %r' % to)
    to = S(to)
    if to not in TRANSITIONS.get(S(alert.status), set()):
        raise WorkflowError('cannot move an alert from %s to %s' % (alert.status, to))
    if to in SUPERVISOR_ONLY and not is_supervisor(user):
        raise PermissionError('only a supervisor can move an alert to %s' % to)
    if to in NOTE_REQUIRED and not note.strip():
        raise WorkflowError('a note explaining the decision is required for %s' % to)

    with transaction.atomic():
        previous = alert.status
        alert.status = to
        if to == S.INVESTIGATING and alert.assigned_to is None:
            alert.assigned_to = user
        alert.save(update_fields=['status', 'assigned_to', 'updated_at'])
        if note.strip():
            AlertNote.objects.create(alert=alert, author=user, text=note.strip())
        record(user, 'alert.status_changed', alert, previous=previous, to=to, note=note.strip())
    return alert


def assign(alert, assignee, user):
    if alert.is_closed:
        raise WorkflowError('alert is closed')
    previous = alert.assigned_to.username if alert.assigned_to else None
    alert.assigned_to = assignee
    alert.save(update_fields=['assigned_to', 'updated_at'])
    record(user, 'alert.assigned', alert, previous=previous, to=assignee.username)
    return alert
