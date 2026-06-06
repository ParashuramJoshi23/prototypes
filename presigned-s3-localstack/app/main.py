import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import s3


@asynccontextmanager
async def lifespan(app: FastAPI):
    s3.ensure_bucket()
    yield


app = FastAPI(title="Presigned S3 Upload Demo", lifespan=lifespan)


class UploadRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/presign/upload")
def request_upload(req: UploadRequest):
    """Return a pre-signed PUT URL the client uses to upload directly to S3."""
    key = f"uploads/{uuid.uuid4().hex}/{req.filename}"
    return s3.generate_upload_url(key, req.content_type)


@app.get("/presign/download/{key:path}")
def request_download(key: str):
    """Return a pre-signed GET URL the client uses to download an object from S3."""
    try:
        return s3.generate_download_url(key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/files")
def list_files():
    """List all objects currently in the bucket."""
    return s3.list_objects()
