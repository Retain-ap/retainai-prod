# backend/storage.py
import os, json, datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATA_ROOT     = os.getenv("DATA_ROOT", "./data")
USE_SQLITE    = os.getenv("USE_SQLITE", "false").lower() == "true"
SQLITE_PATH   = os.getenv("SQLITE_PATH", os.path.join(DATA_ROOT, "retainai.db"))

Path(DATA_ROOT).mkdir(parents=True, exist_ok=True)

# ---------- JSON fallback paths ----------
USERS_JSON = os.path.join(DATA_ROOT, "users.json")
LEADS_JSON = os.path.join(DATA_ROOT, "leads.json")
TEAM_JSON  = os.path.join(DATA_ROOT, "team.json")

def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# ---------- SQLite setup ----------
Base = declarative_base()
engine = None
SessionLocal = None

class User(Base):
    __tablename__ = "users"
    email         = Column(String, primary_key=True)
    password      = Column(String, default="")
    name          = Column(String, default="")
    business      = Column(String, default="")         # businessName
    businessType  = Column(String, default="")
    teamSize      = Column(String, default="")
    logo          = Column(Text, default="")
    location      = Column(String, default="")
    status        = Column(String, default="pending_payment")
    trial_start   = Column(String, default="")
    trial_ending_notice_sent = Column(Integer, default=0)  # 0/1

    leads         = relationship("Lead", back_populates="user", cascade="all, delete-orphan")

class Lead(Base):
    __tablename__ = "leads"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_email       = Column(String, ForeignKey("users.email"))
    name             = Column(String, default="")
    email            = Column(String, default="")
    phone            = Column(String, default="")
    tags             = Column(String, default="")            # comma-separated
    notes            = Column(Text, default="")
    createdAt        = Column(String, default="")
    last_contacted   = Column(String, default="")

    user             = relationship("User", back_populates="leads")

def _init_sqlite():
    global engine, SessionLocal
    if engine is not None:
        return
    uri = f"sqlite:///{SQLITE_PATH}"
    engine = create_engine(uri, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

def _ensure_sqlite():
    if not USE_SQLITE:
        return
    _init_sqlite()

# ---------- Public API used by app.py ----------
def load_users() -> Dict[str, Dict[str, Any]]:
    if not USE_SQLITE:
        return _read_json(USERS_JSON, {})
    _ensure_sqlite()
    with SessionLocal() as s:
        users = s.query(User).all()
        out = {}
        for u in users:
            out[u.email] = {
                "email": u.email,
                "password": u.password,
                "name": u.name,
                "business": u.business,
                "businessType": u.businessType,
                "teamSize": u.teamSize,
                "logo": u.logo,
                "location": u.location,
                "status": u.status,
                "trial_start": u.trial_start,
                "trial_ending_notice_sent": bool(u.trial_ending_notice_sent),
            }
        return out

def save_users(users_map: Dict[str, Dict[str, Any]]) -> None:
    if not USE_SQLITE:
        _write_json(USERS_JSON, users_map)
        return
    _ensure_sqlite()
    with SessionLocal() as s:
        # upsert users from dict
        for email, data in users_map.items():
            u = s.get(User, email)
            if not u:
                u = User(email=email)
            u.password     = data.get("password","")
            u.name         = data.get("name","")
            u.business     = data.get("business","")
            u.businessType = data.get("businessType","")
            u.teamSize     = data.get("teamSize","")
            u.logo         = data.get("logo","")
            u.location     = data.get("location","")
            u.status       = data.get("status","pending_payment")
            u.trial_start  = data.get("trial_start","")
            u.trial_ending_notice_sent = 1 if data.get("trial_ending_notice_sent") else 0
            s.merge(u)
        s.commit()

def get_user(email:str) -> Optional[Dict[str, Any]]:
    if not USE_SQLITE:
        return load_users().get(email)
    _ensure_sqlite()
    with SessionLocal() as s:
        u = s.get(User, email)
        if not u:
            return None
        return {
            "email": u.email,
            "password": u.password,
            "name": u.name,
            "business": u.business,
            "businessType": u.businessType,
            "teamSize": u.teamSize,
            "logo": u.logo,
            "location": u.location,
            "status": u.status,
            "trial_start": u.trial_start,
            "trial_ending_notice_sent": bool(u.trial_ending_notice_sent),
        }

def create_user(data: Dict[str, Any]) -> None:
    if not USE_SQLITE:
        users = load_users()
        users[data["email"]] = data
        save_users(users)
        return
    _ensure_sqlite()
    with SessionLocal() as s:
        u = User(
            email=data["email"],
            password=data.get("password",""),
            name=data.get("name",""),
            business=data.get("business",""),
            businessType=data.get("businessType",""),
            teamSize=data.get("teamSize",""),
            logo=data.get("logo",""),
            location=data.get("location",""),
            status=data.get("status","pending_payment"),
            trial_start=data.get("trial_start",""),
            trial_ending_notice_sent=1 if data.get("trial_ending_notice_sent") else 0,
        )
        s.merge(u)
        s.commit()

def load_leads() -> Dict[str, List[Dict[str, Any]]]:
    if not USE_SQLITE:
        return _read_json(LEADS_JSON, {})
    _ensure_sqlite()
    with SessionLocal() as s:
        out: Dict[str, List[Dict[str, Any]]] = {}
        all_leads = s.query(Lead).all()
        for L in all_leads:
            out.setdefault(L.user_email, []).append({
                "id": L.id,
                "name": L.name,
                "email": L.email,
                "phone": L.phone,
                "tags": L.tags,
                "notes": L.notes,
                "createdAt": L.createdAt,
                "last_contacted": L.last_contacted,
            })
        return out

def save_leads(leads_by_user: Dict[str, List[Dict[str, Any]]]) -> None:
    if not USE_SQLITE:
        _write_json(LEADS_JSON, leads_by_user)
        return
    _ensure_sqlite()
    with SessionLocal() as s:
        # drop & replace for simplicity (small scale)
        s.query(Lead).delete()
        for user_email, leads in leads_by_user.items():
            for ld in leads:
                s.add(Lead(
                    user_email=user_email,
                    name=ld.get("name",""),
                    email=ld.get("email",""),
                    phone=ld.get("phone",""),
                    tags=ld.get("tags",""),
                    notes=ld.get("notes",""),
                    createdAt=ld.get("createdAt",""),
                    last_contacted=ld.get("last_contacted",""),
                ))
        s.commit()

# ---------- One-time migration from JSON to SQLite ----------
def migrate_json_to_sqlite_if_needed():
    if not USE_SQLITE:
        return
    _ensure_sqlite()
    # Only migrate if DB is empty of users (first run)
    with SessionLocal() as s:
        has_users = s.query(User).limit(1).first() is not None
        if has_users:
            return
    # Load JSON and write into DB
    users = _read_json(USERS_JSON, {})
    leads = _read_json(LEADS_JSON, {})
    if users:
        save_users(users)
    if leads:
        save_leads(leads)
