from sqlalchemy.orm import Session

from app.models import VideoProcessing


def create_video(
    db: Session, video_id: str, filename: str, file_path: str, trace_id: str
) -> VideoProcessing:
    video = VideoProcessing(
        video_id=video_id,
        filename=filename,
        file_path=file_path,
        status="queued",
        trace_id=trace_id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def get_video(db: Session, video_id: str) -> VideoProcessing | None:
    return db.query(VideoProcessing).filter(VideoProcessing.video_id == video_id).first()


def update_status(db: Session, video_id: str, status: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.status = status
    db.commit()


def update_transcript(db: Session, video_id: str, transcript: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.transcript = transcript
    db.commit()


def update_summary(db: Session, video_id: str, summary: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.summary = summary
    db.commit()


def update_bulletpoints(db: Session, video_id: str, bulletpoints: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.bulletpoints = bulletpoints
    db.commit()


def update_action_items(db: Session, video_id: str, action_items: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.action_items = action_items
    db.commit()


def update_translation(db: Session, video_id: str, translation: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.translation = translation
    db.commit()


def update_thumbnail(db: Session, video_id: str, thumbnail_path: str) -> None:
    video = get_video(db, video_id)
    if not video:
        return
    video.thumbnail_path = thumbnail_path
    db.commit()
