# Transaction Monitoring System

![CI](https://github.com/MayhurJoker007/transaction-monitoring/actions/workflows/ci.yml/badge.svg)

A bank-style transaction monitoring backend. Core banking posts transactions in, a separate screening service runs
them through configurable detection rules, and analysts work the resulting alerts through a case workflow. Every
action lands in an append-only audit log.

**Stack:** Python 3.12, Django, Django REST Framework, PostgreSQL, Celery + Redis, Docker, Kubernetes manifests
(EKS-ready), GitHub Actions.

```
 core banking ──POST /api/transactions/──► API pods ──(on commit)──► Redis ──► screening workers
                (idempotent, batch ok)       │                                   │ rules engine
                                             ▼                                   ▼
                                         PostgreSQL ◄────────────── alerts, risk score, audit log
                                             ▲
                analysts / supervisors ──────┘  /api/alerts/  /api/rules/  /api/audit/
```

## Detection rules

| Rule | Default | Severity |
|---|---|---|
| `LARGE_AMOUNT` | per account type: cheque R50 000, savings R100 000, business R500 000 | medium |
| `CASH_THRESHOLD` | cash deposit above R49 999.99 | high |
| `STRUCTURING` | 3+ cash deposits within 20% under the threshold inside 24h | high |
| `VELOCITY` | more than 10 debits in 60 minutes | medium |
| `DUPLICATE` | same amount to the same counterparty within 10 minutes | low |
| `DORMANT_REACTIVATION` | debit of R5 000+ from an account that was dormant | medium |
| `HIGH_RISK_CUSTOMER` | R20 000+ by a customer rated high risk | medium |

Thresholds live in the database (`RuleConfig`), so compliance can tune or disable a rule through the API
without a deploy. Changes are supervisor-only, validated (unknown parameters are rejected) and audited with
before and after values. The figures above are configurable defaults for a demo, not legal thresholds.

Alerts explain themselves:

```
STRUCTURING          3 cash deposits between R39 999.99 and R49 999.99 in 24h, R132 085.04 in total
DUPLICATE            same R4 500.00 to 4071234567 as SIM-fdf4975a32b6, 4 min earlier
DORMANT_REACTIVATION debit of R18 000.00 on an account that was dormant
LARGE_AMOUNT         R75 000.00 is at or above the cheque limit of R50 000.00
```

That's real output from `python manage.py simulate`, which pushes 300 ordinary transactions and a handful of
planted patterns through the real ingestion path. Every planted pattern is caught, and none of the ordinary
transactions trigger a large-amount or cash alert.

## Design decisions

**Ingestion and screening are separate services.** The API only validates, stores and queues. Screening runs on
its own Celery queue in its own Kubernetes deployment, so a backlog of screening never slows down ingestion, and
each side scales independently.

**Nothing is lost or doubled:**
- `external_id` is unique, so a re-sent batch returns `duplicate` for rows already stored.
- Screening is queued with `transaction.on_commit`, so a worker never looks for a row that isn't committed yet.
- `acks_late` means a worker that dies mid-task doesn't drop the transaction, and retries back off exponentially.
- A unique (transaction, rule) constraint means a retried screening can't raise the same alert twice.
- A broken rule (for example a bad parameter) is logged and skipped. It doesn't stop the other rules.

**Batches are accepted line by line.** One bad row in 500 gets a `207 Multi-Status` with the reason, and the
other 499 go through.

**Dormancy is captured at ingestion.** Recording the transaction updates the account's last activity, so
whether the account *was* dormant is stored on the transaction for screening to use later.

## Alert workflow and roles

```
open ──► investigating ──► escalated ──► closed_reported        (supervisor only)
  │            │               │
  └────────────┴───────────────┴──► closed_false_positive
```

- Escalating or closing needs a note explaining the decision.
- Taking an alert into investigation assigns it to you.
- Roles are Django groups: **ingest** (service accounts that can only post transactions), **analyst** and
  **supervisor**. An ingest token can't read alerts, and an analyst can't change rules or read the audit log.
- Audit entries can't be updated or deleted, in the ORM or in the admin.

## Running it

```
docker compose up --build
docker compose exec api python manage.py seed_demo      # prints API tokens for each role
docker compose exec api python manage.py simulate
```

```
curl -H "Authorization: Token <analyst token>" "localhost:8000/api/alerts/?status=open&severity=high"
```

Without Docker (SQLite, tasks run inline):

```
pip install -r requirements-dev.txt
set CELERY_TASK_ALWAYS_EAGER=true
python manage.py migrate && python manage.py seed_demo && python manage.py simulate
python manage.py runserver
```

### Kubernetes

`k8s/` has the deployment for AWS EKS (or any cluster): an API deployment with a migration init container,
readiness and liveness probes (`/readyz` checks the database), an HPA, a non-root read-only filesystem, and a
separate screening-worker deployment with a graceful shutdown period. Config comes from a ConfigMap, and secrets
from a Secret (fed by AWS Secrets Manager in a real setup).

## Tests

```
pytest
```

The 17 tests cover idempotent and batch ingestion, every rule (including tuned and disabled rules), re-screening
not duplicating alerts, the full alert workflow including supervisor-only reporting and required notes, role
enforcement on every endpoint group, audited rule changes, the append-only audit log, and health checks. CI runs
them against PostgreSQL 16 and builds the Docker image.
