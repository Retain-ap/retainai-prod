# backend/storage.py
"""
RetainAI storage adapter (PROD-SAFE)

Goals:
- Keep app.py unchanged.
- Support BOTH JSON fallback and SQLite persistence.
- Store "users" as a dict keyed by email.
- Store "leads" as a dict keyed by user_email, each value is a list of lead dicts.
- Avoid schema drift problems by storing full records as JSON blobs in SQLite
  (so app.py can add new fields without migrations).

Env:
- DATA_ROOT (default ./data)
- USE_SQLITE ("true"/"false")
- SQLITE_PATH (default DATA_ROOT/retainai.db)
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, Column, String, Text, ForeignKey, Index
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ----------------------------
# ENV / PATHS
# ----------------------------
DATA_ROOT = os.getenv("DATA_ROOT", "./data")
USE_SQLITE = (os.getenv("USE_SQLITE", "false") or "").lower() == "true"
SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(DATA_ROOT, "retainai.db"))

Path(DATA_ROOT).mkdir(parents=True, exist_ok=True)

# JSON fallback paths
USERS_JSON = os.path.join(DATA_ROOT, "users.json")
LEADS_JSON = os.path.join(DATA_ROOT, "leads.json")
TEAM_JSON = os.path.join(DATA_ROOT, "team.json")  # kept for legacy compatibility


# ----------------------------
# JSON helpers
# ----------------------------
def _read_json(path: str, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        # last-resort: stringify non-serializable values
        def _coerce(x):
            try:
                json.dumps(x)
                return x
            except Exception:
                return str(x)

        if isinstance(obj, dict):
            return json.dumps({str(k): _coerce(v) for k, v in obj.items()}, ensure_ascii=False)
        if isinstance(obj, list):
            return json.dumps([_coerce(v) for v in obj], ensure_ascii=False)
        return json.dumps(_coerce(obj), ensure_ascii=False)


def _safe_json_loads(s: str, default):
    try:
        if not s:
            return default
        return json.loads(s)
    except Exception:
        return default


# ----------------------------
# SQLite setup (JSON blob storage)
# ----------------------------
Base = declarative_base()
engine = None
SessionLocal = None


class UserRow(Base):
    __tablename__ = "users"

    email = Column(String, primary_key=True)
    # full user dict as JSON string (includes password/status/stripe/tokens/etc)
    data = Column(Text, default="{}")

    leads = relationship("LeadRow", back_populates="user", cascade="all, delete-orphan")


class LeadRow(Base):
    __tablename__ = "leads"

    # IMPORTANT: app.py uses UUID strings for lead["id"]
    id = Column(String, primary_key=True)
    user_email = Column(String, ForeignKey("users.email"), index=True)
    # full lead dict as JSON string (includes tags list, status, birthday, wa_opt_out, etc)
    data = Column(Text, default="{}")

    user = relationship("UserRow", back_populates="leads")


Index("idx_leads_user_email", LeadRow.user_email)


def _sqlite_columns(conn, table_name: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    return {r[1] for r in rows}


def ensure_sqlite_schema(_engine) -> None:
    """
    Heal existing Render persistent DB schema to match current models.
    Fixes: sqlite3.OperationalError: no such column: users.data
    """
    with _engine.begin() as conn:
        # Create minimal users table if missing
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                data TEXT
            )
            """
        )

        cols = _sqlite_columns(conn, "users")
        if "data" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN data TEXT")

        # Create minimal leads table if missing
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                user_email TEXT,
                data TEXT
            )
            """
        )

        # Ensure leads has required columns
        lcols = _sqlite_columns(conn, "leads")
        if "user_email" not in lcols:
            conn.exec_driver_sql("ALTER TABLE leads ADD COLUMN user_email TEXT")
        if "data" not in lcols:
            conn.exec_driver_sql("ALTER TABLE leads ADD COLUMN data TEXT")

        # Index (safe if already exists)
        try:
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_leads_user_email ON leads(user_email)")
        except Exception:
            pass


def _init_sqlite():
    global engine, SessionLocal

    if engine is not None and SessionLocal is not None:
        return

    # ensure parent dir exists for absolute paths like /var/retainai/retainai.db
    try:
        Path(os.path.dirname(SQLITE_PATH) or ".").mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    uri = f"sqlite:///{SQLITE_PATH}"
    engine = create_engine(
        uri,
        future=True,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    # ✅ heal schema BEFORE ORM touches it
    ensure_sqlite_schema(engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)


def _ensure_sqlite():
    if not USE_SQLITE:
        return
    _init_sqlite()


# ----------------------------
# Public API used by app.py
# ----------------------------
def load_users() -> Dict[str, Dict[str, Any]]:
    """
    Returns:
      { "<email>": {user dict...}, ... }
    """
    if not USE_SQLITE:
        data = _read_json(USERS_JSON, {})
        return data if isinstance(data, dict) else {}

    _ensure_sqlite()
    out: Dict[str, Dict[str, Any]] = {}
    with SessionLocal() as s:
        for row in s.query(UserRow).all():
            d = _safe_json_loads(row.data, {})
            if not isinstance(d, dict):
                d = {}
            d["email"] = (d.get("email") or row.email or "").strip().lower()
            out[row.email] = d
    return out


def save_users(users_map: Dict[str, Dict[str, Any]]) -> None:
    """
    Upserts users from dict.
    """
    if not USE_SQLITE:
        _write_json(USERS_JSON, users_map if isinstance(users_map, dict) else {})
        return

    _ensure_sqlite()
    if not isinstance(users_map, dict):
        users_map = {}

    with SessionLocal() as s:
        for email, data in users_map.items():
            em = (email or (data or {}).get("email") or "").strip().lower()
            if not em:
                continue

            row = s.get(UserRow, em)
            if not row:
                row = UserRow(email=em)

            if not isinstance(data, dict):
                data = {}
            data = dict(data)
            data["email"] = em

            row.data = _safe_json_dumps(data)
            s.merge(row)

        s.commit()


def get_user(email: str) -> Optional[Dict[str, Any]]:
    email = (email or "").strip().lower()
    if not email:
        return None

    if not USE_SQLITE:
        users = load_users()
        u = users.get(email)
        return u if isinstance(u, dict) else None

    _ensure_sqlite()
    with SessionLocal() as s:
        row = s.get(UserRow, email)
        if not row:
            return None
        d = _safe_json_loads(row.data, {})
        if not isinstance(d, dict):
            d = {}
        d["email"] = email
        return d


def create_user(data: Dict[str, Any]) -> None:
    """
    Creates or updates a user.
    app.py sometimes uses dict-map upsert; this is still safe to call.
    """
    if not isinstance(data, dict):
        return
    email = (data.get("email") or "").strip().lower()
    if not email:
        return

    if not USE_SQLITE:
        users = load_users()
        users[email] = dict(data, email=email)
        save_users(users)
        return

    _ensure_sqlite()
    with SessionLocal() as s:
        row = s.get(UserRow, email) or UserRow(email=email)
        payload = dict(data, email=email)
        row.data = _safe_json_dumps(payload)
        s.merge(row)
        s.commit()


def load_leads() -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns:
      { "<user_email>": [lead dict, ...], ... }
    """
    if not USE_SQLITE:
        data = _read_json(LEADS_JSON, {})
        return data if isinstance(data, dict) else {}

    _ensure_sqlite()
    out: Dict[str, List[Dict[str, Any]]] = {}
    with SessionLocal() as s:
        rows = s.query(LeadRow).all()
        for row in rows:
            user_email = (row.user_email or "").strip().lower()
            if not user_email:
                continue
            d = _safe_json_loads(row.data, {})
            if not isinstance(d, dict):
                d = {}
            d["id"] = str(d.get("id") or row.id or "")
            out.setdefault(user_email, []).append(d)

    # keep stable ordering if createdAt exists
    try:
        for _, arr in out.items():
            arr.sort(key=lambda x: (x.get("createdAt") or x.get("created_at") or ""), reverse=False)
    except Exception:
        pass

    return out


def save_leads(leads_by_user: Dict[str, List[Dict[str, Any]]]) -> None:
    """
    Persist leads. For simplicity and safety at small scale:
    - In SQLite: delete all leads and re-insert from leads_by_user.
      (Prevents mismatch between app uuid string IDs and older integer IDs.)
    """
    if not USE_SQLITE:
        _write_json(LEADS_JSON, leads_by_user if isinstance(leads_by_user, dict) else {})
        return

    _ensure_sqlite()
    if not isinstance(leads_by_user, dict):
        leads_by_user = {}

    with SessionLocal() as s:
        # Wipe and replace (small-scale safe)
        s.query(LeadRow).delete()

        # Ensure user rows exist for foreign keys (best-effort)
        for user_email in list(leads_by_user.keys()):
            ue = (user_email or "").strip().lower()
            if not ue:
                continue
            if not s.get(UserRow, ue):
                s.add(UserRow(email=ue, data=_safe_json_dumps({"email": ue})))

        for user_email, leads in leads_by_user.items():
            ue = (user_email or "").strip().lower()
            if not ue or not isinstance(leads, list):
                continue

            for ld in leads:
                if not isinstance(ld, dict):
                    continue

                lid = ld.get("id")
                lid = str(lid) if lid is not None else ""
                if not lid:
                    lid = f"lead_{ue}_{abs(hash(_safe_json_dumps(ld))) % (10**12)}"
                    ld["id"] = lid

                payload = dict(ld)
                payload["id"] = lid

                s.add(
                    LeadRow(
                        id=lid,
                        user_email=ue,
                        data=_safe_json_dumps(payload),
                    )
                )

        s.commit()


# ----------------------------
# One-time migration JSON -> SQLite
# ----------------------------
def migrate_json_to_sqlite_if_needed():
    """
    If USE_SQLITE=true:
      - Only migrates if SQLite has no users yet.
      - Moves users.json and leads.json into SQLite.
    """
    if not USE_SQLITE:
        return

    _ensure_sqlite()

    with SessionLocal() as s:
        has_users = s.query(UserRow).limit(1).first() is not None
        if has_users:
            return

    users = _read_json(USERS_JSON, {})
    leads = _read_json(LEADS_JSON, {})

    if isinstance(users, dict) and users:
        save_users(users)
    if isinstance(leads, dict) and leads:
        save_leads(leads)