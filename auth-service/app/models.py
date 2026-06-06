import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=True)  # null for SSO-only accounts
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    # org / tenant for SSO/SCIM multi-tenancy
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    oauth_accounts = relationship("OAuthAccount", back_populates="user", cascade="all, delete-orphan")
    tenant = relationship("Tenant", back_populates="users")


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)          # "google" | "github" | "oidc"
    provider_user_id = Column(String, nullable=False)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="oauth_accounts")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Tenant(Base):
    """Represents an organisation/tenant for SSO and SCIM."""
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    # OIDC SSO config
    sso_issuer = Column(String, nullable=True)        # OIDC discovery URL base
    sso_client_id = Column(String, nullable=True)
    sso_client_secret = Column(String, nullable=True)
    sso_domain = Column(String, nullable=True)        # email domain → auto-redirect
    # SCIM
    scim_token_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    users = relationship("User", back_populates="tenant")
