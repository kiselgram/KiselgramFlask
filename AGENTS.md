# AGENTS.md

Guidance for LLM coding agents working in the Kiselgram repository.

## Mandatory rule (do NOT violate)

Every time you make ANY change to this project (code, bugfixes, new features,
refactoring, settings, docs), you MUST synchronously update `CHANGELOG.txt`
in the project root:

1. Open `CHANGELOG.txt`.
2. In **section 3 ("WHAT WAS ADDED THIS TIME")** append a short description of
   each change (what exactly, which files).
3. If functionality changed — bump the **version** in "CURRENT VERSION"
   (free-form scheme, e.g. v4.7.1.2).
4. If you noticed new problems/ideas — add them to **section 2** (problems)
   or **section 4** (what to add next).
5. Stamp the date on every update.

This rule ALWAYS applies and needs no extra user prompt. Even if the user did
not mention CHANGELOG — update it anyway.

## What this is

Kiselgram is a self-hosted, modern messaging platform (personal chats, groups, broadcast
channels, stories, video calls, bots, premium) built with **Flask (Python 3.10+)**, SQLAlchemy,
and a **vanilla JavaScript (ES6+) SPA** with no framework. UI text is in Russian.

## Commands

```bash
# run the app (Flask on :5000 + video server on :5001)
python manage.py start [--port 5000] [--no-video] [--no-browser] [--video-port 5001]

# stop / restart / status
python manage.py stop
python manage.py restart
python manage.py status

# first-time setup: generates config/kis.toml, initializes the DB, creates admin
python manage.py setup

# drop & recreate the database
python manage.py reset_db

# run the test suite
pytest                       # or: python manage.py test

# typecheck / lint
mypy app/                    # .mypy_cache present in repo
ruff check app/ tests/       # .ruff_cache present; no pyproject/ruff config file — defaults apply
```

There is **no** `routes`, `backup-db`, or `shell` command in `manage.py` — do not reference them.

## Run & environment

- Always use the project interpreter: `.venv/bin/python` (system `python`/`python3`
  lack dependencies — `ModuleNotFoundError: No module named 'flask'`).
- JS check: `node --check static/js/k/<file>.js`.
- **Tests run against the FILE database** `instance/kiselgram.db` (the
  `conftest.py` URI override happens after engine creation) and **truncate all
  tables per test**. Never run `pytest` against production data; dev data in
  `instance/` will be wiped.
- Shell here is `zsh`; avoid `timeout` (not installed), heredocs inside the
  `bash` tool are unreliable — prefer the file tools for writing files.

## Project layout

- `manage.py` — CLI entrypoint and app factory (`create_app()` in `app/__init__.py`).
- `app/models.py` — **58 SQLAlchemy models** (42 core: `User`, `Message`, `Chat`, `Story`, `Call`,
  `VideoCall`, `Poll`, `UserSession`, `UserPremium`, `Contact`, `InviteLink`, `Referral`, ...;
  plus 12 `Sputnik*` and 4 `Tg*` (topics, live location, bot commands, collectibles),
  see `docs/models.md` for the full reference).
- **Telegram parity pack** (`app/routes/spav2/telegram.py`, `spav2_telegram_bp`, routes
  `/tg/...`, frontend `static/js/k/tg.js`, `tests/test_telegram.py`,
  see `docs/telegram.md`).
- `app/routes/spav2/` — the V2 JSON API. One module per feature:
  `auth`, `login_v3`, `qr_login`, `oauth`, `chat`, `messages`, `features`, `groups`, `channels`,
  `contacts`, `stories`, `profile`, `calls`, `search`, `sessions`, `saved`, `music`, `ksettings`,
  `referrals`, `push`, `bot_webhook`, `admin`.
- `app/routes/premium.py` — `premium_bp` mounted at `/premium`; prices/promos live in
  `app/routes/premium.toml` and `premium.json` (`PREMIUM_CONFIG_PATH = __file__ / 'premium.toml'`).
- `app/routes/files.py`, `app/routes/video_integration.py` — uploads and video integration.
- `app/config.py` — config; `config/kis.toml` is the generated config file.
- `static/js/k/` — SPA modules: `init.js`, `chat.js`, `groups.js`, `channels.js`, `stories.js`,
  `calls.js`, `premium.js`, `admin.js`, `auth.js`, `features.js`, `profile.js`, `search.js`, `ui.js`.
- **Sputnik ideas pack** (ported from `ilyyagoncharow12/sputnik`, see `docs/sputnik-pack.md`):
  `app/routes/spav2/sputnik.py` (`spav2_sputnik_bp`, prefix `/api`, all routes under
  `/sputnik/...`), `sputnik_pages_bp` (root landing pages `/join/<code>`, `/c/<code>`,
  registered in `app/__init__.py`, template `templates/sputnik_join.html`),
  14 `Sputnik*` models in `app/models.py`, `static/js/k/sputnik.js` (loaded in
  `templates/k.html` AFTER `features.js`), `tests/test_sputnik{,2,3}.py`.
- `tests/` — pytest suite; fixtures: `app`, `client`, `session`, `clear_rate_limiter`, users
  `user/user2/user3/admin_user/premium_user`, `personal_chat`, logged-in clients, helper
  `login_as(client, user)`.

## API conventions

- Frontend globals (from `static/js/k/init.js`): `V2 = '/api.v2/api'`, `V3 = '/api.v3'`.
- The `/api.v2` master blueprint mounts per-feature sub-blueprints → endpoints look like
  `/api.v2/api/messages/send`, `/api.v2/api/groups/create`, `/api.v2/api/stories/feed`.
- Mounted **outside** `/api.v2`: `/api/push` (push), `/api/admin` (admin), `/api/bots`
  (`bot_webhook.py`), `/video/integration/...` (video), `/files/...` and `/uploads/...` (uploads),
  `/health`, `/stats`, `/endpoints`, `/ping`, `/test/env`, `/test/env/shutdown` (utils).
- Guards: `@login_required` (bearer `UserSession.session_token`), `@admin_required` (admin),
  `@rate_limit(name, max_requests=..., window=...)` (login, register, OTP, resend).
- Responses are JSON; errors return `{success: false, error: "..."}` with appropriate status.
- Username rule error text: *"Username must be 3-32 characters (letters, numbers, underscores)"*.

## Conventions

- Flask-SQLAlchemy models in `app/models.py`; use `db.Column`, `db.ForeignKey('user.id', ondelete='CASCADE')`.
- Follow the pattern of existing endpoints (decorator + `@login_required`, JSON request/response).
- Message encryption at rest uses AES-256-GCM (Fernet) via `MESSAGE_ENCRYPTION_KEY`; the
  `Message` model has `is_encrypted`, `encrypted_content`, `encryption_key_id`.
- Video call defaults: `VIDEO_DEFAULT_PORT = os.environ.get('VIDEO_PORT', '5001')`,
  `VIDEO_TIMEOUT = 5` in `app/routes/spav2/calls.py`.
- License is **Proprietary** (see `LICENSE`); do not state MIT.

## Verify before finishing

Run the relevant tests (`pytest`), then `ruff check` and `mypy app/` on any changed Python files.
Full human-readable docs live in the sibling repo `kiselgram-docs` (see `components/` there).

## Things that are easy to break

- **Auth model**: `get_current_user_id()` accepts Bearer `UserSession` token OR cookie
  session. `require_csrf()` in `app/utils/security.py` exists but is opt-in — enabling it
  globally breaks cookie-authenticated clients and tests.
- **New write endpoints**: always gate chat access via `_chat_access(uid, chat_id)` from
  `app/routes/spav2/features.py` (members for groups/personal via `ChatMember`,
  subscribers/owner/admins for channels). Never trust client-supplied `chat_id` alone.
- **Presence**: never return `last_seen`/`is_online` raw — use `presence_visible(viewer_id, user)`
  from `app/utils/helpers.py` (honors `privacy_last_seen`).
- **Paths**: `safe_path_in_uploads()` in `app/routes/files.py` must keep the
  `+ os.sep` check — a bare `startswith()` allows sibling dirs (`uploads_evil/`).
- **Encryption vs search**: `Message.content` is encrypted at rest; `LIKE`/`in` filters on
  plaintext only work after decryption in Python (see `search_messages` pattern).
- **Frontend**: `sputnik.js` monkey-patches `K.chat._messageHtml` (guarded by `_spWrapped`)
  and self-mounts nav/composer/story buttons (guarded by element ids). Its body-wide
  `MutationObserver` must stay cheap — network calls only from the debounced
  per-container observer and on chat-switch key change.
- **Blueprints**: API blueprints go through `Api2._load_bps()` (auto-duplicated under
  `/api.v3`); root-level pages need a separate blueprint registered in `app/__init__.py`.
- **DB DDL in tests**: tables are created once per pytest session against the file DB;
  if you change a model constraint, drop the affected tables in `instance/kiselgram.db`
  first or `create_all(checkfirst)` will keep the stale schema.
- **In-memory stores** (`RateLimiter._store`, `_ACCOUNT_FAILURES`, `KISELGRAM_USER_ID`)
  persist across tests in one pytest process and do not work across workers.

## Known pre-existing failures (not caused by recent work, verified on pristine tree)

- `tests/test_auth.py`, `tests/test_chats.py` fail (legacy SPA expectations).
- Parts of `tests/test_spav2_admin.py`, `tests/test_spav2_search.py` fail.
- `tests/test_client_api.py` hangs order-dependently at
  `test_activate_premium_already_premium` (passes standalone).
- `mypy` reports repo-wide patterns (`db.Model` dynamic base, missing stubs) —
  only errors mentioning your new symbols are yours.
