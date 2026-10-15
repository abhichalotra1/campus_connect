# Campus Connect

A campus placement portal built with Django. Students browse and apply to placement drives, recruiters post drives and manage applicants, and admins verify recruiters and monitor the platform.

## Roles

| Role | Can do |
|---|---|
| Student | Build a profile, browse drives, apply, withdraw, view interviews and notifications |
| Recruiter | Request verification, post and edit drives (once verified), review applicants, shortlist or reject, schedule interviews |
| Admin | Verify recruiters, moderate drives and users, view stats, export student data (CSV) |

## Tech stack

Django 6, SQLite (local) / PostgreSQL (Render), django-allauth (account only, used so users can log in with username or email), WhiteNoise, Bootstrap (CDN).

## Run locally

```bash
git clone <your-repo-url> campus_connect
cd campus_connect
git checkout lite

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env        # Windows: copy .env.example .env
# edit .env and set SECRET_KEY

python manage.py migrate
python manage.py createsuperuser
# then make it an app admin (see "Admin account" below)
python manage.py runserver
```

Open http://127.0.0.1:8000/.

## Admin account

`createsuperuser` makes a Django superuser, but the app decides access by the `role` field, and new users default to `student`. After creating the superuser, make it an app admin:

```bash
python manage.py shell -c "from accounts.models import User; User.objects.filter(username='<your-username>').update(role='admin')"
```

## Environment variables

| Variable | Needed | Purpose |
|---|---|---|
| `SECRET_KEY` | Always | Django secret key |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | For emails | Gmail SMTP login (App Password) |
| `RENDER` | Production | Turns on Render settings |
| `DATABASE_URL` | Production | PostgreSQL connection string |

## Deploy on Render

- Build command: `./build.sh`
- Start command: `gunicorn campus_connect.wsgi`
- Set the environment variables above in the Render dashboard.

Known limitation: uploaded files (resumes, logos, profile pictures) are stored on the server disk and are lost on redeploy until persistent media storage is added. This is on the fix list.

## Project layout

```
accounts/       users, roles, login/register, admin dashboard, stats, exports
students/       student and recruiter profiles
placements/     drives, applications, interviews
notifications/  in-app notifications
campus_connect/ settings, URLs, email helpers
templates/      HTML templates
```