# backend/app_imports.py
from flask import Blueprint, request, jsonify, redirect, Response, session
import os, time, json, requests, hashlib, csv, io, re
from urllib.parse import urlencode
from uuid import uuid4
from storage import DATA_ROOT, load_leads, save_user_leads

def _load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- Config ----------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# UNIQUE redirect URI for People/Contacts (avoid conflict with Calendar OAuth)
GOOGLE_PEOPLE_REDIRECT_URI = os.getenv(
    "GOOGLE_PEOPLE_REDIRECT_URI",
    "http://localhost:5000/api/google/people/oauth-callback",
)

# Prefer FRONTEND_BASE; fall back to FRONTEND_URL; then localhost
FRONTEND_BASE = (
    os.getenv("FRONTEND_BASE")
    or os.getenv("FRONTEND_URL")
    or "http://localhost:3000"
)

# People API scope (notes require contacts.readonly); include basic identity
GOOGLE_SCOPE = "openid email profile https://www.googleapis.com/auth/contacts.readonly"

print("[GOOGLE PEOPLE AUTH] client_id=", GOOGLE_CLIENT_ID)
print("[GOOGLE PEOPLE AUTH] redirect_uri=", GOOGLE_PEOPLE_REDIRECT_URI)

# ---------- Blueprint ----------
imports_bp = Blueprint("imports_bp", __name__)

# ---------- Storage for Google tokens/sync ----------
TOKENS_FILE = os.getenv("GOOGLE_TOKENS_FILE", "google_tokens.json")   # per-user tokens
SYNC_FILE   = os.getenv("GOOGLE_SYNC_FILE",   "google_sync.json")     # nextSyncToken
IMPORT_HISTORY_FILE = os.path.join(DATA_ROOT, "import_history.json")

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _normalize_email(e):
    return (e or "").strip().lower()

def _load_leads_bucket(user_email):
    all_leads = load_leads()
    return all_leads.get(user_email) or []

def _save_leads_bucket(user_email, leads):
    save_user_leads(user_email, leads)

def _request_user_email():
    session_user = str(session.get("user_email") or session.get("email") or "").strip().lower()
    header_user = str(request.headers.get("X-User-Email") or "").strip().lower()
    return session_user or header_user

def _clean_phone(value, country_code="+1"):
    raw = str(value or "").strip()
    if not raw:
        return ""
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if has_plus:
        return f"+{digits}"
    prefix = re.sub(r"\D", "", str(country_code or "+1"))
    if len(digits) == 10 and prefix:
        return f"+{prefix}{digits}"
    return f"+{digits}"

def _lead_identity(row):
    email = str(row.get("email") or "").strip().lower()
    phone = re.sub(r"\D", "", str(row.get("phone") or ""))
    return email, phone

def _remember_import(user_email, before, after, summary, label):
    history = _load_json_file(IMPORT_HISTORY_FILE, {})
    rows = history.setdefault(user_email, [])
    entry = {
        "id": str(uuid4()), "created_at": int(time.time()), "label": label,
        "before": before, "after_count": len(after), "summary": summary,
    }
    rows.insert(0, entry)
    history[user_email] = rows[:10]
    _save_json_file(IMPORT_HISTORY_FILE, history)
    return {k: v for k, v in entry.items() if k != "before"}

# ---------- Token helpers ----------
def _set_token(user_email, token_payload):
    tokens = _load_json(TOKENS_FILE, {})
    tokens[user_email] = token_payload
    _save_json(TOKENS_FILE, tokens)

def _get_token(user_email):
    tokens = _load_json(TOKENS_FILE, {})
    return tokens.get(user_email)

def _set_sync_token(user_email, sync_token):
    syncs = _load_json(SYNC_FILE, {})
    syncs[user_email] = {"sync_token": sync_token, "updated_at": int(time.time())}
    _save_json(SYNC_FILE, syncs)

def _get_sync_token(user_email):
    syncs = _load_json(SYNC_FILE, {})
    entry = syncs.get(user_email)
    return entry.get("sync_token") if entry else None

def _exchange_code_for_tokens(code):
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_PEOPLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    r = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=20)
    r.raise_for_status()
    return r.json()

def _refresh_access_token(refresh_token):
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    r = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=20)
    r.raise_for_status()
    return r.json()

# ---------- People API helpers ----------
def _fetch_connections(access_token, *, page_token=None, request_sync_token=False, sync_token=None):
    """
    Returns dict like the People API response, or markers:
      {"expired_sync": True}  -> HTTP 410
      {"forbidden": <error>}  -> HTTP 403
    """
    params = {
        "personFields": "names,emailAddresses,phoneNumbers,organizations,biographies,photos,birthdays",
        "pageSize": 1000,
    }
    if page_token:
        params["pageToken"] = page_token
    if request_sync_token:
        params["requestSyncToken"] = "true"
    if sync_token:
        params["syncToken"] = sync_token

    headers = {"Authorization": f"Bearer {access_token}"}
    url = "https://people.googleapis.com/v1/people/me/connections?" + urlencode(params)
    r = requests.get(url, headers=headers, timeout=30)

    if r.status_code == 410:
        return {"expired_sync": True}
    if r.status_code == 403:
        try:
            body = r.json()
        except Exception:
            body = {"error": {"message": r.text}}
        return {"forbidden": body}

    r.raise_for_status()
    return r.json()

# ---------- Mapping & identity hardening ----------
def _sha10(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:10]

def _stable_pseudo_email(resource_name: str, name: str, emails: list, phones: list) -> str:
    """
    Create a stable, unique pseudo-email for contacts lacking an email,
    so the UI still treats each contact as distinct AND stable across re-imports.
    """
    if resource_name:
        h = _sha10(resource_name)
        return f"people_{h}@google.local"
    base = f"{(name or '').strip()}|{sorted(emails or [])}|{sorted(phones or [])}|google"
    h = _sha10(base)
    return f"people_{h}@google.local"

def _map_person_to_lead(person):
    names = person.get("names") or []
    display_name = ""
    if names:
        display_name = names[0].get("displayName") or (
            (names[0].get("givenName") or "") + " " + (names[0].get("familyName") or "")
        ).strip()

    emails = [e.get("value") for e in (person.get("emailAddresses") or []) if e.get("value")]
    phones = [p.get("value") for p in (person.get("phoneNumbers") or []) if p.get("value")]

    resource_name = person.get("resourceName")  # e.g., "people/abc123"

    # If no real email, synthesize a unique, stable pseudo email
    primary_email = emails[0] if emails else _stable_pseudo_email(resource_name, display_name, emails, phones)

    birthday = None
    for b in (person.get("birthdays") or []):
        d = b.get("date")
        if not d:
            continue
        y, m, day = d.get("year"), d.get("month"), d.get("day")
        if not (m and day):
            continue
        birthday = (f"{int(y):04d}-" if y else "0000-") + f"{int(m):02d}-{int(day):02d}"
        break

    orgs = person.get("organizations") or []
    company = orgs[0].get("name") if orgs else None
    title   = orgs[0].get("title") if orgs else None
    bios = person.get("biographies") or []
    notes = bios[0].get("value") if bios else None

    return {
        "name": display_name or primary_email,
        "emails": emails,
        "email": primary_email,
        "phones": phones,
        "phone": (phones[0] if phones else None),
        "company": company,
        "title": title,
        "notes": notes,
        "birthday": birthday,
        "source": "google",
        "external_id": resource_name
    }

def _ensure_unique_ids(leads):
    """Guarantee each lead has a unique id; backfill any missing/duplicate ids."""
    seen = set()
    changed = False
    out = []
    for l in leads or []:
        l = dict(l)
        lid = l.get("id")
        if not lid or lid in seen:
            l["id"] = str(uuid4())
            changed = True
        seen.add(l["id"])
        out.append(l)
    return out, changed

# ---------- Upsert / Merge (SAFE: by external_id ONLY) ----------
def _upsert_leads_google(user_email, mapped):
    existing = _load_leads_bucket(user_email)

    # Index by external_id only (primary key for Google contacts)
    idx_ext = {}
    for i, ld in enumerate(existing):
        ext = ld.get("external_id")
        if ext:
            idx_ext[ext] = i

    imported = merged = skipped = 0
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def merge_list(a, b):
        a = a or []
        seen = set([x for x in a if x])
        out = list(a)
        for x in (b or []):
            if x and x not in seen:
                out.append(x)
                seen.add(x)
        return out

    for row in mapped:
        ext = row.get("external_id")
        emails = row.get("emails") or []
        phones = row.get("phones") or []

        if ext and ext in idx_ext:
            # Merge into existing by external_id only
            i = idx_ext[ext]
            t = existing[i]

            if not t.get("id"):
                t["id"] = str(uuid4())

            t["name"]     = t.get("name") or row.get("name")
            t["company"]  = t.get("company") or row.get("company")
            t["title"]    = t.get("title") or row.get("title")
            t["birthday"] = t.get("birthday") or row.get("birthday")

            if row.get("notes"):
                t["notes"] = (t.get("notes") + "\n" + row["notes"]) if t.get("notes") else row["notes"]

            t["phones"] = merge_list(t.get("phones"), phones)
            if not t.get("phone"):
                t["phone"] = row.get("phone") or (t["phones"][0] if t.get("phones") else None)

            t["emails"] = merge_list(t.get("emails") or ([t.get("email")] if t.get("email") else []), emails)
            if not t.get("email"):
                t["email"] = row.get("email") or (t["emails"][0] if t.get("emails") else _stable_pseudo_email(ext, row.get("name"), emails, phones))

            if ext and not t.get("external_id"):
                t["external_id"] = ext

            t.setdefault("owner", user_email)
            t.setdefault("source", "google")
            t.setdefault("last_contacted", now_iso)
            t.setdefault("createdAt", now_iso)

            existing[i] = t
            merged += 1

        else:
            # New record
            new_ld = {
                "id": str(uuid4()),
                "name": row.get("name"),
                "email": row.get("email"),
                "emails": emails,
                "phone": row.get("phone"),
                "phones": phones,
                "company": row.get("company"),
                "title": row.get("title"),
                "notes": row.get("notes"),
                "birthday": row.get("birthday"),
                "tags": ["Imported"],
                "source": "google",
                "external_id": ext,
                "createdAt": now_iso,
                "last_contacted": now_iso,
                "owner": user_email
            }
            existing.append(new_ld)
            if ext:
                idx_ext[ext] = len(existing) - 1
            imported += 1

    existing, changed = _ensure_unique_ids(existing)
    if changed:
        print(f"[GOOGLE IMPORT] normalized lead IDs for {user_email}")

    _save_leads_bucket(user_email, existing)
    return {
        "imported": imported,
        "merged": merged,
        "skipped": skipped,
        "total_after": len(existing)
    }

# ---------- Popup HTML ----------
def _popup_finish_html(redirect_to, query=None, message="Google import finished. You can close this window."):
    try:
        qs = "?" + urlencode(query or {})
    except Exception:
        qs = ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Done</title>
<style>
  body{{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0f1115;color:#e6e6e6;
       display:flex;align-items:center;justify-content:center;height:100vh}}
  a{{color:#ffd666}}
</style>
</head><body>
  <div>{message}</div>
<script>
(function() {{
  var redirect = {json.dumps(redirect_to)} + {json.dumps(qs)};
  try {{
    if (window.opener && !window.opener.closed) {{
      try {{ window.opener.postMessage({{ type: 'google-import-complete', ok: true }}, '*'); }} catch (e) {{}}
      window.close();
      return;
    }}
  }} catch (e) {{}}
  if (redirect) {{
    try {{ window.location.replace(redirect); }} catch (e) {{ window.location = redirect; }}
  }}
}})();
</script>
</body></html>"""

def _popup_close_html(msg="Google import finished. You can close this window."):
    # On error/missing info, return to dashboard
    return _popup_finish_html(FRONTEND_BASE + "/app", {}, msg)

# ---------- Routes ----------
@imports_bp.post("/api/import/csv/preview")
def csv_preview():
    user_email = _request_user_email()
    if not user_email:
        return jsonify({"error": "Sign in again before importing contacts."}), 401
    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".csv"):
        return jsonify({"error": "Choose a CSV file."}), 400
    raw = upload.read()
    if len(raw) > 5 * 1024 * 1024:
        return jsonify({"error": "CSV files must be 5 MB or smaller."}), 413
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    headers = [str(value or "").strip() for value in (reader.fieldnames or [])]
    aliases = {
        "name": ["name", "full name", "customer", "contact"],
        "first_name": ["first name", "firstname", "given name"],
        "last_name": ["last name", "lastname", "surname", "family name"],
        "email": ["email", "email address", "e-mail"],
        "phone": ["phone", "phone number", "mobile", "whatsapp"],
        "company": ["company", "business", "organization"],
        "title": ["title", "job title", "role"],
        "notes": ["notes", "note", "description"],
    }
    lower = {header.lower(): header for header in headers}
    suggested = {key: next((lower[item] for item in values if item in lower), "") for key, values in aliases.items()}
    existing = _load_leads_bucket(user_email)
    existing_email = {str(item.get("email") or "").lower() for item in existing if item.get("email")}
    existing_phone = {re.sub(r"\D", "", str(item.get("phone") or "")) for item in existing if item.get("phone")}
    rows = []
    for index, row in enumerate(reader):
        if index >= 5000:
            break
        normalized = {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        email = normalized.get(suggested["email"], "").lower()
        phone = _clean_phone(normalized.get(suggested["phone"], ""))
        rows.append({
            "raw": normalized, "selected": True,
            "name": normalized.get(suggested["name"], ""), "email": email, "phone": phone,
            "duplicate": bool((email and email in existing_email) or (phone and re.sub(r"\D", "", phone) in existing_phone)),
        })
    if not rows:
        return jsonify({"error": "The CSV did not contain any contact rows."}), 400
    return jsonify({"headers": headers, "mapping": suggested, "rows": rows, "total_rows": len(rows), "preview_count": len(rows)}), 200


@imports_bp.post("/api/import/csv/commit")
def csv_commit():
    user_email = _request_user_email()
    if not user_email:
        return jsonify({"error": "Sign in again before importing contacts."}), 401
    body = request.get_json(silent=True) or {}
    rows = body.get("rows") or []
    mapping = body.get("mapping") or {}
    mode = str(body.get("duplicate_mode") or "skip").lower()
    if mode not in {"skip", "update", "merge"}:
        return jsonify({"error": "Choose skip, update, or merge for duplicates."}), 400
    country_code = str(body.get("country_code") or "+1")
    tag = str(body.get("tag") or "CSV import").strip()[:80]
    existing = _load_leads_bucket(user_email)
    before = json.loads(json.dumps(existing))
    imported = merged = updated = skipped = invalid = 0
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def value(raw, key):
        return str((raw or {}).get(mapping.get(key) or key) or "").strip()

    for item in rows[:5000]:
        if item.get("selected") is False:
            skipped += 1
            continue
        raw = item.get("raw") or item
        first, last = value(raw, "first_name"), value(raw, "last_name")
        name = value(raw, "name") or f"{first} {last}".strip()
        email = value(raw, "email").lower()
        phone = _clean_phone(value(raw, "phone"), country_code)
        if not (name or email or phone):
            invalid += 1
            continue
        incoming = {
            "name": name or email or phone, "email": email, "phone": phone,
            "company": value(raw, "company"), "title": value(raw, "title"), "notes": value(raw, "notes"),
        }
        match = next((lead for lead in existing if (email and str(lead.get("email") or "").lower() == email) or (phone and re.sub(r"\D", "", str(lead.get("phone") or "")) == re.sub(r"\D", "", phone))), None)
        if match:
            if mode == "skip":
                skipped += 1
                continue
            for key, val in incoming.items():
                if val and (mode == "update" or not match.get(key)):
                    match[key] = val
            match["tags"] = sorted(set((match.get("tags") or []) + ([tag] if tag else [])))
            match["updated_at"] = now_iso
            updated += mode == "update"
            merged += mode == "merge"
            continue
        existing.append({
            "id": str(uuid4()), **incoming, "owner": user_email, "source": "csv",
            "tags": [tag] if tag else [], "createdAt": now_iso, "updated_at": now_iso,
        })
        imported += 1
    _save_leads_bucket(user_email, existing)
    summary = {"imported": imported, "merged": merged, "updated": updated, "skipped": skipped, "invalid": invalid, "total_after": len(existing)}
    entry = _remember_import(user_email, before, existing, summary, body.get("file_name") or "CSV import")
    return jsonify({"ok": True, "summary": summary, "import": entry}), 200


@imports_bp.get("/api/import/history")
def import_history():
    user_email = _request_user_email()
    if not user_email:
        return jsonify({"error": "Sign in again."}), 401
    history = _load_json_file(IMPORT_HISTORY_FILE, {}).get(user_email, [])
    return jsonify({"imports": [{k: v for k, v in row.items() if k != "before"} for row in history]}), 200


@imports_bp.post("/api/import/<import_id>/undo")
def undo_import(import_id):
    user_email = _request_user_email()
    if not user_email:
        return jsonify({"error": "Sign in again."}), 401
    history = _load_json_file(IMPORT_HISTORY_FILE, {})
    rows = history.get(user_email, [])
    entry = next((row for row in rows if row.get("id") == import_id), None)
    if not entry or not isinstance(entry.get("before"), list):
        return jsonify({"error": "That import can no longer be undone."}), 404
    _save_leads_bucket(user_email, entry["before"])
    history[user_email] = [row for row in rows if row.get("id") != import_id]
    _save_json_file(IMPORT_HISTORY_FILE, history)
    return jsonify({"ok": True, "restored_contacts": len(entry["before"])}), 200


@imports_bp.route("/api/google/status")
def google_status():
    user_email = (request.args.get("userEmail") or "").strip().lower()
    if not user_email:
        return jsonify({"error": "missing_userEmail"}), 400
    tokens = _get_token(user_email)
    sync_tok = _get_sync_token(user_email)
    leads = _load_leads_bucket(user_email)
    return jsonify({
        "google_connected": bool(tokens),
        "has_refresh_token": bool(tokens and tokens.get("refresh_token")),
        "token_obtained_at": (tokens or {}).get("obtained_at"),
        "sync_token_present": bool(sync_tok),
        "leads_count": len(leads),
    })

@imports_bp.route("/api/google/import-now", methods=["POST"])
def google_import_now():
    payload = request.json or {}
    user_email = (payload.get("userEmail") or "").strip().lower()
    if not user_email:
        return jsonify({"error": "missing_userEmail"}), 400

    tok = _get_token(user_email)
    if not tok:
        return jsonify({"error": "not_connected"}), 400

    access_token = tok.get("access_token")
    refresh_token = tok.get("refresh_token")
    if refresh_token:
        try:
            new_tok = _refresh_access_token(refresh_token)
            access_token = new_tok.get("access_token") or access_token
            for k, v in new_tok.items():
                if v is not None:
                    tok[k] = v
            tok["obtained_at"] = int(time.time())
            _set_token(user_email, tok)
        except Exception as e:
            print("[GOOGLE IMPORT NOW] refresh failed:", e)

    try:
        sync_token = _get_sync_token(user_email)
        all_people, page_token, new_sync = [], None, None
        want_sync_token = False if sync_token else True

        while True:
            resp = _fetch_connections(
                access_token,
                page_token=page_token,
                request_sync_token=want_sync_token if not sync_token else False,
                sync_token=sync_token
            )

            if resp.get("forbidden"):
                body_json = json.dumps(resp["forbidden"])
                if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in body_json:
                    print("[GOOGLE IMPORT NOW] insufficient scope; clearing token to force fresh consent")
                    try:
                        tokens = _load_json(TOKENS_FILE, {})
                        tokens.pop(user_email, None)
                        _save_json(TOKENS_FILE, tokens)
                    except Exception:
                        pass
                    return jsonify({"status": "error", "error": "insufficient_scope"}), 400

                print("[GOOGLE IMPORT NOW] 403 requesting sync token; retrying without it. Body:", resp["forbidden"])
                want_sync_token = False
                page_token = None
                all_people = []
                sync_token = None
                continue

            if resp.get("expired_sync"):
                print("[GOOGLE IMPORT NOW] sync token expired; full resync")
                sync_token = None
                page_token = None
                all_people = []
                want_sync_token = True
                continue

            all_people.extend(resp.get("connections") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                new_sync = resp.get("nextSyncToken") or sync_token
                break

        mapped = [_map_person_to_lead(p) for p in all_people]
        summary = _upsert_leads_google(user_email, mapped)
        if new_sync:
            _set_sync_token(user_email, new_sync)

        print(f"[GOOGLE IMPORT NOW] user={user_email} fetched={len(all_people)} summary={summary} new_sync={'yes' if new_sync else 'no'}")
        return jsonify({"status": "ok", "fetched": len(all_people), "summary": summary})
    except requests.HTTPError as e:
        try:
            body = e.response.json()
        except Exception:
            body = {"text": getattr(e.response, "text", str(e))}
        print("[GOOGLE IMPORT NOW] HTTP error:", e, "body:", body)
        return jsonify({"status": "error", "error": "people_api_failed", "details": body}), 500
    except Exception as e:
        print("[GOOGLE IMPORT NOW] error:", e)
        return jsonify({"status": "error", "error": "people_api_failed"}), 500

@imports_bp.route("/api/google/debug-list")
def google_debug_list():
    user_email = (request.args.get("userEmail") or "").strip().lower()
    if not user_email:
        return jsonify({"error": "missing_userEmail"}), 400
    tok = _get_token(user_email)
    if not tok:
        return jsonify({"error": "not_connected"}), 400

    access_token = tok.get("access_token")
    try:
        resp = _fetch_connections(access_token, page_token=None, request_sync_token=False)
        if resp.get("forbidden"):
            return jsonify({"error": "forbidden", "details": resp["forbidden"]}), 403
        conns = resp.get("connections") or []
        sample = []
        for p in conns[:10]:
            names = p.get("names") or []
            name = names[0].get("displayName") if names else None
            emails = [e.get("value") for e in (p.get("emailAddresses") or []) if e.get("value")]
            phones = [ph.get("value") for ph in (p.get("phoneNumbers") or []) if ph.get("value")]
            sample.append({"name": name, "emails": emails, "phones": phones})
        return jsonify({"count": len(conns), "sample": sample})
    except requests.HTTPError as e:
        try:
            body = e.response.json()
        except Exception:
            body = {"text": getattr(e.response, "text", str(e))}
        print("[GOOGLE DEBUG LIST] HTTP error:", e, "body:", body)
        return jsonify({"error": "people_api_failed", "details": body}), 500
    except Exception as e:
        print("[GOOGLE DEBUG LIST] error:", e)
        return jsonify({"error": "people_api_failed"}), 500

@imports_bp.route("/api/google/authorize")
def google_authorize():
    user_email = (request.args.get("userEmail") or request.headers.get("X-User-Email") or "").strip().lower()
    # DEFAULT: return to dashboard unless caller passes a redirect
    redirect_to = request.args.get("redirect") or f"{FRONTEND_BASE}/app"
    if not user_email:
        return Response(_popup_close_html(), mimetype="text/html", status=400)

    state = json.dumps({"u": user_email, "r": redirect_to})
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_PEOPLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "false",  # force fresh consent so People scope is included
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(url)

@imports_bp.route("/api/google/people/oauth-callback")
def google_people_oauth_callback():
    error = request.args.get("error")
    state_raw = request.args.get("state")
    code = request.args.get("code")

    # default if state missing -> dashboard
    redirect_to = FRONTEND_BASE + "/app"
    user_email = ""

    try:
        if state_raw and state_raw.strip().startswith("{"):
            state = json.loads(state_raw)
            user_email = (state.get("u") or "").strip().lower()
            redirect_to = (state.get("r") or redirect_to)
        else:
            user_email = (state_raw or "").strip().lower()
    except Exception:
        user_email = (state_raw or "").strip().lower()

    if error or (not code) or (not user_email):
        return Response(_popup_finish_html(redirect_to, message="Google authorization failed or was cancelled."), mimetype="text/html", status=400)

    # Exchange auth code → tokens
    try:
        token_payload = _exchange_code_for_tokens(code)
    except Exception as e:
        print("[GOOGLE PEOPLE OAUTH] token exchange failed:", e)
        return Response(_popup_finish_html(redirect_to, message="Could not obtain Google tokens."), mimetype="text/html", status=400)

    access_token = token_payload.get("access_token")
    token_payload["obtained_at"] = int(time.time())
    _set_token(user_email, token_payload)

    # Full import (first time). If 403 on requesting sync token, retry without it.
    try:
        all_people, page_token, sync_token = [], None, None
        want_sync_token = True

        while True:
            resp = _fetch_connections(
                access_token,
                page_token=page_token,
                request_sync_token=want_sync_token
            )

            if resp.get("forbidden"):
                body = resp["forbidden"]
                body_json = json.dumps(body) if not isinstance(body, str) else body
                if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in body_json:
                    print("[GOOGLE PEOPLE OAUTH] insufficient scope; clearing saved token to force fresh consent")
                    try:
                        tokens = _load_json(TOKENS_FILE, {})
                        tokens.pop(user_email, None)
                        _save_json(TOKENS_FILE, tokens)
                    except Exception:
                        pass
                    return Response(_popup_finish_html(redirect_to, message="Insufficient Google scope. Please try again."), mimetype="text/html", status=400)

                print("[GOOGLE PEOPLE OAUTH] 403 when requesting sync token; retrying without sync token. Body:", body)
                want_sync_token = False
                page_token = None
                all_people = []
                continue

            if resp.get("expired_sync"):
                print("[GOOGLE PEOPLE OAUTH] received expired sync; doing full resync")
                want_sync_token = True
                page_token = None
                all_people = []
                continue

            all_people.extend(resp.get("connections") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                sync_token = resp.get("nextSyncToken") or sync_token
                break

        mapped = [_map_person_to_lead(p) for p in all_people]
        summary = _upsert_leads_google(user_email, mapped)
        if sync_token:
            _set_sync_token(user_email, sync_token)

        print(f"[GOOGLE PEOPLE OAUTH] user={user_email} fetched={len(all_people)} summary={summary} new_sync={'yes' if sync_token else 'no'}")
    except requests.HTTPError as e:
        try:
            body = e.response.json()
        except Exception:
            body = {"text": getattr(e.response, "text", str(e))}
        print("[GOOGLE PEOPLE OAUTH] people API failed:", e, "body:", body)
        # Even on failure, send the user back to the app so they can retry
        return Response(_popup_finish_html(redirect_to, message="Google import failed. You can retry from the app."), mimetype="text/html", status=200)
    except Exception as e:
        print("[GOOGLE PEOPLE OAUTH] people API failed:", e)
        return Response(_popup_finish_html(redirect_to, message="Google import failed. You can retry from the app."), mimetype="text/html", status=200)

    # Success → return to caller (dashboard by default)
    return Response(_popup_finish_html(redirect_to, message="Import complete!"), mimetype="text/html", status=200)
