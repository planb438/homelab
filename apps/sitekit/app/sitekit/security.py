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


import base64, struct, time


def totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, at: float = None, step: int = 30) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((at if at is not None else time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def totp_ok(secret: str, code: str, at: float = None) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != 6 or not code.isdigit():
        return False
    t = at if at is not None else time.time()
    return any(hmac.compare_digest(totp_code(secret, t + d * 30), code) for d in (-1, 0, 1))
