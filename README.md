# MedicalConsultations — Backend

Django REST API for the MedicalConsultations system.

## Stack
- Python 3.13 + Django (LTS) + Django REST Framework
- PostgreSQL 16, Redis 7 (cache)
- JWT auth (djangorestframework-simplejwt)
- Modular monolith: `config/` + apps under `apps/`

## Modules
`accounts` `centers` `doctors` `patients` `records` `medicines` `appointments`

See `../infra/docs/architecture.md` for the full design.
