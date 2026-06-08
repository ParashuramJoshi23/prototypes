"""SCIM 2.0 endpoints.

Implements the core User resource. Groups are stubbed but structurally present.
Authentication is a per-tenant static bearer token validated in `require_scim_token`.

Spec: https://datatracker.ietf.org/doc/html/rfc7644
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_scim_token
from app.models import User
from app.schemas import (
    ScimListResponse,
    ScimUserCreate,
    ScimUserOut,
    ScimUserPatch,
    ScimName,
    ScimEmail,
)

router = APIRouter(
    prefix="/scim/v2",
    tags=["scim"],
    dependencies=[Depends(require_scim_token)],
)

SCIM_CONTENT_TYPE = "application/scim+json"


def _user_to_scim(user: User, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": user.id,
        "userName": user.email,
        "name": {
            "formatted": user.username or "",
            "givenName": "",
            "familyName": "",
        },
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": user.is_active,
        "externalId": None,
        "meta": {
            "resourceType": "User",
            "location": f"{base}/scim/v2/Users/{user.id}",
            "created": user.created_at.isoformat() if user.created_at else None,
            "lastModified": user.updated_at.isoformat() if user.updated_at else None,
        },
    }


# ── Service Provider Config ───────────────────────────────────────────────────

@router.get("/ServiceProviderConfig")
def service_provider_config():
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer Token",
                "description": "OAuth Bearer Token",
            }
        ],
    }


@router.get("/ResourceTypes")
def resource_types(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 2,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
                "meta": {"location": f"{base}/scim/v2/ResourceTypes/User", "resourceType": "ResourceType"},
            },
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "Group",
                "name": "Group",
                "endpoint": "/Groups",
                "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
                "meta": {"location": f"{base}/scim/v2/ResourceTypes/Group", "resourceType": "ResourceType"},
            },
        ],
    }


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/Users")
def list_users(
    request: Request,
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=200),
    filter: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(User)

    # Basic SCIM filter: userName eq "foo@bar.com"
    if filter:
        if 'userName eq "' in filter:
            val = filter.split('userName eq "')[1].rstrip('"')
            query = query.filter(User.email == val)
        elif "userName eq '" in filter:
            val = filter.split("userName eq '")[1].rstrip("'")
            query = query.filter(User.email == val)

    total = query.count()
    users = query.offset(startIndex - 1).limit(count).all()

    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(users),
        "Resources": [_user_to_scim(u, request) for u in users],
    }


@router.post("/Users", status_code=201)
def create_user(body: ScimUserCreate, request: Request, db: Session = Depends(get_db)):
    email = next((e.value for e in body.emails if e.primary), None) or body.userName
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        email=email,
        username=body.userName,
        is_active=body.active,
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_scim(user, request)


@router.get("/Users/{user_id}")
def get_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_scim(user, request)


@router.put("/Users/{user_id}")
def replace_user(user_id: str, body: ScimUserCreate, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    email = next((e.value for e in body.emails if e.primary), None) or body.userName
    user.email = email
    user.username = body.userName
    user.is_active = body.active
    db.commit()
    db.refresh(user)
    return _user_to_scim(user, request)


@router.patch("/Users/{user_id}")
def patch_user(user_id: str, body: ScimUserPatch, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for op in body.Operations:
        operation = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if operation == "replace":
            if path == "active" or (isinstance(value, dict) and "active" in value):
                active_val = value if isinstance(value, bool) else value.get("active", user.is_active)
                user.is_active = active_val
            elif path == "userName":
                user.username = value
            elif isinstance(value, dict):
                if "active" in value:
                    user.is_active = value["active"]
                if "userName" in value:
                    user.username = value["userName"]
        elif operation == "add":
            if path == "active":
                user.is_active = value

    db.commit()
    db.refresh(user)
    return _user_to_scim(user, request)


@router.delete("/Users/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()


# ── Groups (stub) ─────────────────────────────────────────────────────────────

@router.get("/Groups")
def list_groups():
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 0,
        "startIndex": 1,
        "itemsPerPage": 0,
        "Resources": [],
    }


@router.post("/Groups", status_code=201)
def create_group(request: Request):
    raise HTTPException(status_code=501, detail="Groups not yet implemented")
