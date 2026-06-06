import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import crud, image, s3
from app.cdn import get_view_url
from app.config import PRESIGN_EXPIRY_SECONDS
from app.db import Base, engine, get_db
from app.models import PhotoStatus
from app.schemas import (
    PhotoOut,
    UploadRequest,
    UploadResponse,
    UserCreate,
    UserLogin,
    UserOut,
    ViewUrlResponse,
)

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    s3.ensure_bucket()
    yield


app = FastAPI(title="Image Upload Service", lifespan=lifespan)


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/gallery", response_class=HTMLResponse)
def gallery_page(request: Request, user_id: str = ""):
    return templates.TemplateResponse("gallery.html", {"request": request, "user_id": user_id})


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Users ─────────────────────────────────────────────────────────────────────

@app.post("/users/login", response_model=UserOut)
def login(req: UserLogin, db: Session = Depends(get_db)):
    """Create account on first visit, return existing account on return visits."""
    return crud.get_or_create_user(db, email=req.email, username=req.username)


@app.post("/users", response_model=UserOut, status_code=201)
def create_user(req: UserCreate, db: Session = Depends(get_db)):
    return crud.create_user(db, email=req.email, username=req.username)


@app.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/users/{user_id}/photos", response_model=list[PhotoOut])
def list_photos(user_id: uuid.UUID, db: Session = Depends(get_db)):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return crud.list_user_photos(db, user_id)


# ── Photos ────────────────────────────────────────────────────────────────────

@app.post("/photos/upload-url", response_model=UploadResponse, status_code=201)
def request_upload(req: UploadRequest, db: Session = Depends(get_db)):
    """Step 1: client requests a pre-signed PUT URL.

    The service creates a pending photo record and returns the URL.
    The client uploads the file directly to S3, then calls /confirm.
    """
    if not crud.get_user(db, req.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    photo_id = uuid.uuid4()
    ext = req.filename.rsplit(".", 1)[-1].lower() if "." in req.filename else "jpg"
    s3_key = f"photos/{photo_id}/original.{ext}"

    presign = s3.generate_upload_url(s3_key, req.content_type)

    crud.create_photo(
        db,
        photo_id=photo_id,
        user_id=req.user_id,
        filename=req.filename,
        s3_key=s3_key,
        is_private=req.is_private,
    )

    return UploadResponse(
        photo_id=photo_id,
        upload_url=presign["url"],
        s3_key=s3_key,
        method="PUT",
        expires_in=presign["expires_in"],
    )


@app.post("/photos/{photo_id}/confirm", response_model=PhotoOut)
def confirm_upload(photo_id: uuid.UUID, db: Session = Depends(get_db)):
    """Step 2: client calls this after the direct-to-S3 upload completes.

    For private photos the service downloads the original, applies a watermark,
    and re-uploads the processed copy. The original is retained.
    """
    photo = crud.get_photo(db, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    if photo.status != PhotoStatus.pending:
        raise HTTPException(status_code=409, detail=f"Photo already in state '{photo.status}'")

    crud.set_status(db, photo, PhotoStatus.processing)

    try:
        if photo.is_private:
            processed_key = image.process_private_photo(str(photo.id), photo.s3_key)
            crud.set_processed(db, photo, processed_key)
        else:
            crud.set_status(db, photo, PhotoStatus.ready)
    except Exception as exc:
        crud.set_status(db, photo, PhotoStatus.failed)
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    return photo


@app.get("/photos/{photo_id}", response_model=PhotoOut)
def get_photo(photo_id: uuid.UUID, db: Session = Depends(get_db)):
    photo = crud.get_photo(db, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@app.get("/photos/{photo_id}/view", response_model=ViewUrlResponse)
def view_photo(photo_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return a time-limited URL to view the photo.

    Public photos  → CloudFront URL (or S3 pre-signed if CF not configured).
    Private photos → CloudFront signed URL of the watermarked copy.
    """
    photo = crud.get_photo(db, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    if photo.status != PhotoStatus.ready:
        raise HTTPException(status_code=409, detail=f"Photo not ready (status: {photo.status})")

    serve_key = photo.processed_s3_key if photo.is_private else photo.s3_key
    url, via = get_view_url(serve_key)

    return ViewUrlResponse(
        photo_id=photo.id,
        url=url,
        expires_in=PRESIGN_EXPIRY_SECONDS,
        via=via,
    )
