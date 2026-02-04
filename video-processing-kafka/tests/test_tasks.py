import os
import tempfile


def test_task_updates(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        thumb_dir = os.path.join(tmpdir, "thumbs")

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("THUMBNAIL_DIR", thumb_dir)

        from app.db import Base, engine, SessionLocal
        from app.crud import create_video, get_video
        import app.tasks as tasks

        monkeypatch.setattr(tasks, "send_event", lambda *args, **kwargs: None)

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            video_id = "vid123"
            trace_id = "trace123"
            create_video(
                db,
                video_id=video_id,
                filename="file.mp4",
                file_path=os.path.join(tmpdir, "file.mp4"),
                trace_id=trace_id,
            )
        finally:
            db.close()

        class DummyResult:
            def __init__(self):
                self.returncode = 0
                self.stderr = ""

        monkeypatch.setattr(tasks.subprocess, "run", lambda *args, **kwargs: DummyResult())

        tasks.generate_transcript(video_id, "file.mp4", trace_id)
        tasks.add_summary("", video_id=video_id, trace_id=trace_id)
        tasks.add_bulletpoints("", video_id=video_id, trace_id=trace_id)
        tasks.add_action_items("", video_id=video_id, trace_id=trace_id)
        tasks.translate_language("", video_id=video_id, trace_id=trace_id)
        tasks.create_thumbnail("", video_id=video_id, file_path=os.path.join(tmpdir, "file.mp4"), trace_id=trace_id)
        tasks.send_completion("", video_id=video_id, trace_id=trace_id)

        db = SessionLocal()
        try:
            video = get_video(db, video_id)
            assert video is not None
            assert video.status == "complete"
            assert video.transcript
            assert video.summary
            assert video.bulletpoints
            assert video.action_items
            assert video.translation
            assert video.thumbnail_path
        finally:
            db.close()
