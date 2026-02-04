import asyncio
import json
import os
import uuid
from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import KAFKA_TOPIC_UPLOAD, UPLOAD_DIR
from app.crud import create_video, get_video
from app.db import Base, SessionLocal, engine, ensure_schema, get_db
from app.kafka import send_event
from app.logging_config import configure_logging, get_logger
from app.schemas import VideoStatus

Base.metadata.create_all(bind=engine)
ensure_schema()

configure_logging("api")
logger = get_logger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.get("/upload", response_class=HTMLResponse)
def upload_form_alias(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.get("/watch/{video_id}", response_class=HTMLResponse)
def watch_page(request: Request, video_id: str):
    return templates.TemplateResponse(
        "watch.html", {"request": request, "video_id": video_id}
    )


@app.post("/upload")
async def upload_video(file: UploadFile = File(...), db=Depends(get_db)):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    video_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    file_path = os.path.join(UPLOAD_DIR, f"{video_id}-{file.filename}")

    logger.info("upload received", trace_id=trace_id)

    with open(file_path, "wb") as handle:
        content = await file.read()
        handle.write(content)

    create_video(
        db, video_id=video_id, filename=file.filename, file_path=file_path, trace_id=trace_id
    )

    send_event(
        KAFKA_TOPIC_UPLOAD,
        {
            "video_id": video_id,
            "filename": file.filename,
            "file_path": file_path,
            "trace_id": trace_id,
        },
    )

    return {"video_id": video_id, "status": "queued"}


@app.get("/status/{video_id}", response_model=VideoStatus)
def status(video_id: str, db=Depends(get_db)):
    video = get_video(db, video_id)
    if not video:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return video


@app.get("/events/{video_id}")
async def events(video_id: str):
    async def event_stream():
        last_payload = None
        while True:
            db = SessionLocal()
            try:
                video = get_video(db, video_id)
            finally:
                db.close()

            if not video:
                payload = {"error": "not found", "video_id": video_id}
                yield f"data: {json.dumps(payload)}\n\n"
                break

            payload = {
                "video_id": video.video_id,
                "status": video.status,
                "file_path": video.file_path,
                "transcript": video.transcript,
                "summary": video.summary,
                "bulletpoints": video.bulletpoints,
                "action_items": video.action_items,
                "translation": video.translation,
                "thumbnail_path": video.thumbnail_path,
                "updated_at": video.updated_at.isoformat() if video.updated_at else None,
            }
            if payload != last_payload:
                last_payload = payload
                yield f"data: {json.dumps(payload)}\n\n"

            if video.status == "complete":
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
