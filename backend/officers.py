"""Enroll a local officer with python -m backend.officers."""
import getpass
import hashlib
import secrets
import sqlite3
import time
from contextlib import closing

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from threading import Lock
from backend.security_events import event
from backend.config import DATA_DIR
from backend.db.schema import connect, migrate

sessions: dict[str, tuple[str, float]] = {}
session_lock = Lock()
bearer = HTTPBearer(auto_error=False)


def database():
    db = connect(DATA_DIR / "officers.sqlite3")
    try:
        migrate(db, "officers")
    except Exception:
        db.close()
        raise
    return db


def digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def enroll(name, password):
    if not name.strip() or len(name) > 128 or not 12 <= len(password) <= 1024:
        raise ValueError("Enter an officer ID and a password of at least 12 characters.")
    salt = secrets.token_bytes(16)
    with closing(database()) as db, db:
        db.execute("INSERT INTO officers VALUES (?, ?, ?)", (name.strip(), salt, digest(password, salt)))


    event("officer_enrollment", "created", name.strip())


def sign_in(name, password):
    with closing(database()) as db:
        row = db.execute("SELECT salt,digest FROM officers WHERE name=?", (name,)).fetchone()
    if len(password)>1024 or len(name)>128:
        event("sign_in", "denied")
        raise HTTPException(401, "Incorrect officer ID or password.")
    salt, expected = row or (bytes(16), bytes(64))
    if not secrets.compare_digest(expected, digest(password, salt)) or row is None:
        event("sign_in", "denied")
        raise HTTPException(401, "Incorrect officer ID or password.")
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with session_lock:
        for key in [k for k, (_, expires) in sessions.items() if expires <= now]:
            del sessions[key]
        sessions[token] = (name, now + 3600)
    event("sign_in", "success", name)
    return {"officer_id": name, "token": token}


def authenticate_token(token):
    with session_lock:
        session = sessions.get(token)
        if session and session[1] > time.monotonic():
            return session[0]
        sessions.pop(token, None)
    event("access", "denied")
    raise HTTPException(401, "Sign in as a compliance officer.")


def current_officer(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    return authenticate_token(credentials.credentials if credentials else "")


def revoke(token):
    with session_lock:
        session = sessions.pop(token, None)
    if session:
        event("sign_out", "success", session[0])


def enroll_interactively():
    try:
        officer = input("Officer ID: ").strip()
        while not officer:
            officer = input("Enter a non-empty officer ID: ").strip()
        print("Password entry is hidden. Press Enter after each entry.")
        while True:
            password = getpass.getpass("Password (12 or more characters): ")
            if len(password) < 12:
                print("Use at least 12 characters. Try again.")
                continue
            if password != getpass.getpass("Confirm password: "):
                print("Passwords differ. Enter the password again.")
                continue
            enroll(officer, password)
            print("Officer enrolled.")
            return
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("Enrollment canceled.") from None
    except sqlite3.IntegrityError:
        raise SystemExit("That officer ID is already enrolled.") from None


if __name__ == "__main__":
    enroll_interactively()
