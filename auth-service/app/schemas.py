from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, EmailStr, Field


# ── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    username: Optional[str]
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── OAuth ─────────────────────────────────────────────────────────────────────

class OAuthCallbackParams(BaseModel):
    code: str
    state: Optional[str] = None


# ── SSO ──────────────────────────────────────────────────────────────────────

class SSOLoginRequest(BaseModel):
    email: EmailStr  # used to look up tenant by domain


class TenantCreate(BaseModel):
    name: str
    sso_issuer: Optional[str] = None
    sso_client_id: Optional[str] = None
    sso_client_secret: Optional[str] = None
    sso_domain: Optional[str] = None


class TenantOut(BaseModel):
    id: str
    name: str
    sso_domain: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── SCIM 2.0 ─────────────────────────────────────────────────────────────────

class ScimName(BaseModel):
    formatted: Optional[str] = None
    givenName: Optional[str] = None
    familyName: Optional[str] = None


class ScimEmail(BaseModel):
    value: str
    primary: bool = False
    type: str = "work"


class ScimUserCreate(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    userName: str
    name: Optional[ScimName] = None
    emails: list[ScimEmail] = []
    active: bool = True
    externalId: Optional[str] = None


class ScimUserPatch(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    Operations: list[dict[str, Any]]


class ScimUserOut(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    id: str
    userName: str
    name: Optional[ScimName] = None
    emails: list[ScimEmail] = []
    active: bool
    externalId: Optional[str] = None
    meta: dict[str, Any]


class ScimListResponse(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    totalResults: int
    startIndex: int = 1
    itemsPerPage: int
    Resources: list[Any]
