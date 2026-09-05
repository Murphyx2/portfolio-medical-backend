# MedicalConsultations — Backend

Django REST API for a role-based clinic management system: encrypted patient
records, doctor scheduling, appointments, and clinical charting. This is a
**scoped-down demo branch** of a larger production system — see
[What's not included](#whats-not-included-in-this-demo) below before judging
feature completeness.

## Stack

- Python 3.13, Django 5.2 (LTS), Django REST Framework
- PostgreSQL 16, Redis 7 (cache)
- JWT auth (`djangorestframework-simplejwt`) — short-lived access token in
  memory, rotating httpOnly refresh cookie, single-flight refresh on the
  frontend
- Modular monolith: `config/` (settings/urls) + one Django app per domain
  under `apps/`, each owning its own models/serializers/views/tests
- `drf-spectacular` for OpenAPI schema/docs (gated to admin/IT)

## What this demo shows

| App | What it demonstrates |
|---|---|
| `accounts` | Custom `User` model, 6-role RBAC (Admin/Doctor/Receptionist/IT/Nurse/Center Manager), JWT auth with brute-force lockout |
| `patients` | Field-level **encrypted PII** at rest (Fernet), role-based masking, guardian relationships for minors |
| `records` | Clinical charting: draft/completed visit entries, vitals tracking, personal/family history, image attachments served via signed tokens |
| `centers` / `doctors` | Doctor↔center bindings with an approval workflow, schedules, service/room assignment |
| `appointments` | Scheduling with a confirm→complete lifecycle, automatic no-show handling |
| `rooms` / `services` / `medicines` | Reference-data catalogs with server-side caching and signal-based invalidation |
| `core` | Shared audit logging, center-scoped access control, the PII encryption layer itself |

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate on Linux/macOS
pip install -r requirements/dev.txt
cp .env.example .env   # set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, PII_FIELD_KEY
python manage.py migrate
python manage.py create_admin --username admin --email admin@example.com --password "..."
python manage.py seed_demo_data --confirm   # generates synthetic patients + records
python manage.py runserver
```

Or run the full stack via Docker Compose from `../infra` (see that repo's
README).

## Testing

```bash
pytest                    # full suite (in-memory SQLite)
python manage.py check    # Django system checks
```

Tests live in `tests/`, with shared fixtures in `tests/conftest.py`.

## Security notes

- Patient PII (name, birth date, phone, address, email, cédula, NSS) is
  encrypted at rest with Fernet, keyed by `PII_FIELD_KEY` — see
  `apps/core/encryption.py` and `apps/core/fields.py`.
- Every write worth an audit trail goes through `apps/core/services.py::log_audit`.
- Role-based, center-scoped access control lives in `apps/core/permissions.py`
  and `apps/core/services/scoping.py`.
- Media (record images) is served only via short-lived HMAC-signed tokens,
  never static file serving.

## What's not included in this demo

This branch is deliberately scoped down from the full product — these are
real, working capabilities elsewhere, just not shipped here:

- **Insurance (ARS) & negotiated pricing** — Dominican health-insurer
  integration and per-insurer service pricing overrides.
- **Visit/encounter tracking** — service-line-based patient visits with
  co-pago resolution against the pricing above.
- **Patient communications** — WhatsApp (Meta Cloud API) and email
  notifications, appointment reminders, staff messaging.
- **Prescriptions** — structured dose-building and PDF prescription
  generation with a document lifecycle (draft → issued → voided).
- **Operational reporting** — Excel-exportable reports on services rendered
  and insurer settlement packages.

See `../infra/docs/architecture.md` for the full system design.
