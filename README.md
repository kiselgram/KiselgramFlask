# Kiselgram

Flask messaging platform — personal chats, groups, channels, stories, and WebRTC video calls. JSON API with a pure-JS SPA frontend.

[![CI](https://github.com/kiselgram/KiselgramFlask/actions/workflows/ci.yml/badge.svg)](https://github.com/kiselgram/KiselgramFlask/actions/workflows/ci.yml)
[![CD](https://github.com/kiselgram/KiselgramFlask/actions/workflows/cd.yml/badge.svg)](https://github.com/kiselgram/KiselgramFlask/actions/workflows/cd.yml)

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 manage.py setup
python3 manage.py start
```

Visit `http://localhost:5500`

## Management

```bash
python3 manage.py start [--port PORT] [--no-video]
python3 manage.py stop
python3 manage.py restart
python3 manage.py status
python3 manage.py reset-db
python3 manage.py routes
python3 manage.py backup-db
python3 manage.py shell
```

## Testing

```bash
.venv/bin/python -m pytest tests/ -v
```

## Architecture

**Backend:** Python 3 / Flask / SQLAlchemy. Config in `config/kis.toml`. SQLite in dev, PostgreSQL in production (`DATABASE_URL`).

**Two route systems:**
- V1 (`app/routes/spa/`) — legacy session-based, HTML redirects
- V2 (`app/routes/spav2/`) — JSON API, Bearer-token auth under `/api.v2/api/...`

**Auth:** Bearer token (`UserSession.session_token`) with Flask session fallback.

**Message encryption:** AES-256-GCM (Fernet) at rest via `MESSAGE_ENCRYPTION_KEY`.

**Frontend:** Monolithic HTML shell (`templates/k.html`) with 17+ JS modules in `static/js/k/` extending `window.K`. Pure `fetch()`-based SPA.

## Docker deployment

```bash
docker build --platform linux/amd64 -t kiselgram-app:latest .
docker compose up -d
```

Production services: `db` (Postgres 15), `app` (gunicorn), `video` (WebRTC), `mailserver`, `mailadmin`, `nginx`.

## Project structure

| Directory | Purpose |
|-----------|---------|
| `app/` | Flask app, routes, models, utils |
| `static/` | JS, CSS, uploads |
| `templates/` | HTML templates |
| `tests/` | Pytest test suite |
| `config/` | App configuration |
| `video_server/` | WebRTC video calls |
| `mailadmin/` | Mail account management |
| `migrations/` | Alembic DB migrations |

## Domain structure

```
kiselgram.ru              ─ Landing page
web.kiselgram.ru          ─ SPA web app
api.kiselgram.ru          ─ API backend
admin.kiselgram.ru        ─ Admin panel
cdn.kiselgram.ru          ─ Uploaded files
desktop.kiselgram.ru      ─ Desktop downloads
docs.kiselgram.ru         ─ Documentation
help.kiselgram.ru         ─ Help center
call.kiselgram.ru         ─ Video call rooms
```

## License

MIT
