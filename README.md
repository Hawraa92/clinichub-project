# ClinicHub

ClinicHub is a Django-based clinic management system that supports role-based access control, appointments and queue management, medical archiving, and electronic prescriptions with reporting and optional PDF generation.

Repository: **clinichub-project**

---

## Key Features
- **Accounts & Roles**: Admin / Doctor / Secretary / Patient with approval logic (where applicable)
- **Appointments**: Create and manage bookings, prevent time conflicts, auto-generate daily queue numbers per doctor
- **Queue Display**: Public queue display screen + API endpoints for live updates
- **Doctor Area**: Doctor dashboard, patient list, secure patient reports (CSV/PDF)
- **Prescriptions**: Electronic prescriptions with RBAC, public verification via token, optional public PDF (configurable)
- **Medical Archive**: Patient medical archive with multiple attachments, download/preview, and access permissions
- **Testing**: Comprehensive automated tests (project suite runs successfully locally)

---

## Tech Stack
- **Python / Django**
- **PostgreSQL** (recommended for production) + **SQLite** (optional for local development)
- **WhiteNoise** for static files (if enabled in settings)
- **PDF**: WeasyPrint (optional) with fallback (e.g., xhtml2pdf) depending on project configuration
- **Docker** support (Dockerfile + docker-compose)

---

## Requirements
- Python **3.11+** (recommended)
- pip + virtual environment tooling
- (Optional) Docker Desktop

---

## Local Setup (Without Docker)
```bash
python -m venv .venv

# Windows:
.\.venv\Scripts\activate

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver