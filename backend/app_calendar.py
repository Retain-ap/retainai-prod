# backend/app_calendar.py
from flask import Blueprint, request, jsonify, redirect, Response
import os, json, time, requests
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone

calendar_bp = Blueprint("calendar_bp", __name__)

# ---------- Config ----------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# A distinct redirect just for Calendar (separate from People)
GOOGLE_CAL_REDIRECT_URI = os.getenv(
    "GOOGLE_CALENDAR_REDIRECT_URI",
    "http://localhost:5000/api/google/calendar/oauth-callback",
)

# Where to send users after auth completes
FRONTEND_BASE = (
    os.getenv("FRONTEND_BASE")
    or os.getenv("FRONTEND_URL")
    or "http://localhost:3000"
)

# Read-only Calendar is enough to show events
GOOGLE_CAL_SCOPE = "openid email profile https://www.googleapis.com/auth/calendar.readonly"

TOKENS_FILE = os.getenv("GOOGLE_CAL_TOKENS_FILE", "google_calendar_tokens.json")

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _get_token(user_email):
    data = _load_json(TOKENS_FILE, {})
    return data.get(user_email)

def _set_token(user_email, payload):
    data = _load_json(TOKENS_FILE, {})
    data[user_email] = payload
    _save_json(TOKENS_FILE, data)

def _exchange_code_for_tokens(code):
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_CAL_REDIRECT_URI,
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

# ---------- Auth endpoints ----------

@calendar_bp.route("/api/google/calendar/authorize")
def google_calendar_authorize():
    user_email = (request.args.get("userEmail") or request.headers.get("X-User-Email") or "").strip().lower()
    redirect_to = request.args.get("redirect") or f"{FRONTEND_BASE}/app?open=calendar"
    if not user_email:
        return jsonify({"error": "missing_userEmail"}), 400

    state = json.dumps({"u": user_email, "r": redirect_to})
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_CAL_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_CAL_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(url, code=302)

@calendar_bp.route("/api/google/calendar/oauth-callback")
def google_calendar_oauth_callback():
    error = request.args.get("error")
    state_raw = request.args.get("state")
    code = request.args.get("code")

    # default redirect
    redirect_to = f"{FRONTEND_BASE}/app?open=calendar"
    user_email = ""

    try:
        if state_raw and state_raw.strip().startswith("{"):
            st = json.loads(state_raw)
            user_email = (st.get("u") or "").strip().lower()
            redirect_to = st.get("r") or redirect_to
        else:
            user_email = (state_raw or "").strip().lower()
    except Exception:
        user_email = (state_raw or "").strip().lower()

    if error or (not code) or (not user_email):
        return redirect(redirect_to, code=302)

    try:
        tok = _exchange_code_for_tokens(code)
        tok["obtained_at"] = int(time.time())
        _set_token(user_email, tok)
    except Exception as e:
        print("[GOOGLE CAL OAUTH] token exchange failed:", e)
        # still redirect back to app; UI can show a connect button
        return redirect(redirect_to, code=302)

    return redirect(redirect_to, code=302)

# ---------- Events endpoint ----------

@calendar_bp.route("/api/google/events/<user_email>")
def google_list_events(user_email):
    user_email = (user_email or "").strip().lower()
    tok = _get_token(user_email)
    if not tok:
        return jsonify({"error": "not_connected", "hint": "Visit /api/google/calendar/authorize first."}), 401

    access_token = tok.get("access_token")
    refresh_token = tok.get("refresh_token")

    # Refresh if possible (simple strategy: always try if we have a refresh_token and no access_token)
    if (not access_token) and refresh_token:
        try:
            new_tok = _refresh_access_token(refresh_token)
            access_token = new_tok.get("access_token") or access_token
            # merge and persist
            for k, v in new_tok.items():
                if v is not None:
                    tok[k] = v
            tok["obtained_at"] = int(time.time())
            _set_token(user_email, tok)
        except Exception as e:
            print("[GOOGLE CAL EVENTS] refresh failed:", e)

    if not access_token:
        return jsonify({"error": "unauthenticated"}), 401

    # Time window: past 7 days → next 60 days
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=60)).isoformat().replace("+00:00", "Z")

    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 200,
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = requests.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=headers,
            params=params,
            timeout=20,
        )
        if r.status_code == 401 and refresh_token:
            # try one refresh on 401
            try:
                new_tok = _refresh_access_token(refresh_token)
                access_token = new_tok.get("access_token") or access_token
                for k, v in new_tok.items():
                    if v is not None:
                        tok[k] = v
                tok["obtained_at"] = int(time.time())
                _set_token(user_email, tok)
                headers = {"Authorization": f"Bearer {access_token}"}
                r = requests.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers=headers, params=params, timeout=20
                )
            except Exception as e:
                print("[GOOGLE CAL EVENTS] refresh-on-401 failed:", e)

        if not r.ok:
            # bubble up a useful payload to the frontend, not a 500
            try:
                return jsonify({"error": r.json()}), r.status_code
            except Exception:
                return jsonify({"error": r.text}), r.status_code

        data = r.json()
        items = data.get("items", [])

        # Return a light payload the UI can render easily
        simplified = []
        for ev in items:
            simplified.append({
                "id": ev.get("id"),
                "summary": ev.get("summary"),
                "start": (ev.get("start") or {}),
                "end": (ev.get("end") or {}),
                "htmlLink": ev.get("htmlLink"),
                "status": ev.get("status"),
                "creator": (ev.get("creator") or {}),
                "organizer": (ev.get("organizer") or {}),
            })

        return jsonify({
            "items": simplified,
            "raw_count": len(items)
        })
    except requests.HTTPError as e:
        try:
            body = e.response.json()
        except Exception:
            body = {"text": getattr(e.response, "text", str(e))}
        print("[GOOGLE CAL EVENTS] HTTP error:", e, "body:", body)
        return jsonify({"error": "calendar_api_failed", "details": body}), 502
    except Exception as e:
        print("[GOOGLE CAL EVENTS] error:", e)
        return jsonify({"error": "calendar_api_failed"}), 502

@calendar_bp.route("/api/google/calendar/status")
def google_calendar_status():
    user_email = (request.args.get("userEmail") or "").strip().lower()
    if not user_email:
        return jsonify({"error": "missing_userEmail"}), 400
    tok = _get_token(user_email)
    return jsonify({
        "connected": bool(tok),
        "has_refresh_token": bool(tok and tok.get("refresh_token")),
        "obtained_at": (tok or {}).get("obtained_at"),
    })

@calendar_bp.route("/api/google/calendar/disconnect", methods=["POST"])
def google_calendar_disconnect():
    user_email = (request.json or {}).get("userEmail") or ""
    user_email = user_email.strip().lower()
    data = _load_json(TOKENS_FILE, {})
    if user_email in data:
        data.pop(user_email, None)
        _save_json(TOKENS_FILE, data)
    return jsonify({"status": "ok"})
