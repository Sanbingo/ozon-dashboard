"""
Login module for dashboard — session management with 24h expiry
"""
import hashlib
import time
import secrets
import uuid

# Hardcoded users
USERS = {
    "OZON": "000111",
}

# In-memory session store: token -> {"username": str, "expires_at": float}
_sessions = {}


def _hash_password(password):
    """Simple SHA-256 hash for password (basic protection)."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_login(username, password):
    """Check username/password against hardcoded users."""
    stored = USERS.get(username)
    if stored and stored == password:
        return True
    return False


def create_session(username):
    """Create a new session token valid for 24 hours."""
    token = secrets.token_hex(32)
    expires_at = time.time() + 86400  # 24 hours
    _sessions[token] = {
        "username": username,
        "expires_at": expires_at,
    }
    return token, expires_at


def validate_session(token):
    """Check if a session token is valid and not expired."""
    if not token:
        return None
    session = _sessions.get(token)
    if not session:
        return None
    if time.time() > session["expires_at"]:
        # Expired — clean up
        del _sessions[token]
        return None
    return session


def destroy_session(token):
    """Logout: remove session."""
    if token and token in _sessions:
        del _sessions[token]


def cleanup_expired():
    """Remove expired sessions (call periodically)."""
    now = time.time()
    expired = [t for t, s in _sessions.items() if now > s["expires_at"]]
    for t in expired:
        del _sessions[t]
    return len(expired)


def get_cookie_value(cookie_header, name):
    """Parse a cookie header and extract the value for a given cookie name."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1:]
    return None


def session_count():
    return len(_sessions)
