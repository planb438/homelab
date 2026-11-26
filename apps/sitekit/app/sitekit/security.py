"""Passwords, tokens and CSRF. Standard library only."""
import hashlib, hmac, secrets

ITER = 210_000


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), ITER)
    return f"pbkdf2_sha256${ITER}${salt}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(it))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


def token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def csrf_for(secret: str, session_token: str) -> str:
    return hmac.new(secret.encode(), f"csrf:{session_token}".encode(), hashlib.sha256).hexdigest()[:32]
