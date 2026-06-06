import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefreshToken

settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, extra: Optional[dict] = None) -> tuple[str, int]:
    expire = _utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": _utcnow(),
        "type": "access",
        **(extra or {}),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_expire_minutes * 60


def create_refresh_token(user_id: str, db: Session) -> str:
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)

    db.add(RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return raw


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access":
        raise JWTError("not an access token")
    return payload


def rotate_refresh_token(raw: str, db: Session) -> Optional[tuple[str, str, int]]:
    """Validate old refresh token, revoke it, issue new pair. Returns (access, refresh, expires_in)."""
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    record = db.query(RefreshToken).filter_by(token_hash=token_hash, revoked=False).first()
    if not record or record.expires_at.replace(tzinfo=timezone.utc) < _utcnow():
        return None

    record.revoked = True
    db.commit()

    access, expires_in = create_access_token(record.user_id)
    refresh = create_refresh_token(record.user_id, db)
    return access, refresh, expires_in
