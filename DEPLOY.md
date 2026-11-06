# Deploying Campus Connect on Render

## 1. Create the services
1. **PostgreSQL**: New → PostgreSQL. Copy its *Internal Database URL*.
2. **Web Service**: connect this repo, branch `main`.
   - Build command: `./build.sh`  (installs, collects static, migrates, closes expired drives)
   - Start command: `gunicorn campus_connect.wsgi`

## 2. Environment variables (Web Service → Environment)
| Variable | Value |
|---|---|
| `RENDER` | `true` |
| `SECRET_KEY` | 50+ random characters. Generate: `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"` |
| `DATABASE_URL` | the PostgreSQL Internal Database URL |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | Gmail address + **App Password** (not your normal password) |
| `ALLOWED_HOSTS` | only if you add a custom domain (the `*.onrender.com` host is added automatically) |

Leave `DEBUG` unset. It defaults to off.

## 3. Uploaded files (resumes, logos, profile pictures): Cloudinary
Render's disk is wiped on every deploy, so uploads live on Cloudinary (free tier is plenty for a campus).
1. Create a free account at cloudinary.com.
2. Dashboard → *Programmable Media* → **API Keys** → copy the **API Environment variable**. It looks like
   `cloudinary://<api_key>:<api_secret>@<cloud_name>`.
3. Render → your Web Service → Environment → add `CLOUDINARY_URL` with that value. Redeploy.
4. Treat that value like a password. Never commit it or paste it into chat; if it leaks, regenerate the API secret.

How it behaves:
- Profile pictures and company logos are normal Cloudinary image links.
- **Resumes are never linked directly.** Pages link to `/students/resume/<file>`, which allows only the
  student, admins and approved recruiters, then redirects to the file. File names are random, so the
  underlying links can't be guessed. (They are not signed, so anyone who has a link can open it.)
- Without `CLOUDINARY_URL`, files go to the local `media/` folder. That is fine for development, but
  `python manage.py check` prints warning `campus_connect.W001` when `RENDER` is set and Cloudinary is missing.
- Old files are not deleted from Cloudinary when a user replaces them (a possible later clean-up).

## 4. Email on Render
Render's free tier may block outbound SMTP. If welcome / application emails never arrive and the logs show
`[EMAIL] delivery failed`, switch to an HTTPS email API (Resend, Brevo). Emails are sent in a background
thread, so a blocked SMTP port will not slow or break requests; it only means mail is not delivered.

## 5. First deploy checklist
- [ ] Deploy succeeds; build log shows `Closed N expired drives.`
- [ ] Open the site over HTTPS (HTTP redirects to HTTPS)
- [ ] Create the admin: Render Shell → `python manage.py createsuperuser`, then
      `python manage.py shell -c "from accounts.models import User; User.objects.filter(username='YOU').update(role='admin')"`
- [ ] Register a student and a recruiter; confirm welcome emails (or check logs)
- [ ] Admin approves the recruiter; recruiter posts a drive
- [ ] Student completes profile, applies; recruiter shortlists and schedules an interview
- [ ] Upload a resume and a profile picture, redeploy, then reload: both still show
- [ ] A recruiter that is not yet approved cannot open another student's resume link or Search Students
- [ ] Five wrong passwords show the "Too many failed login attempts" page
- [ ] `python manage.py check --deploy` shows no warnings (needs a 50+ char `SECRET_KEY`)

## 6. Housekeeping
- Raise `SECURE_HSTS_SECONDS` in `settings.py` (currently 3600) to `31536000` once everything is stable.
- Expired drives disappear from listings automatically at their deadline. `close_expired_drives`
  only tidies the stored status; it runs on every deploy and can also be scheduled with a Render Cron Job.
