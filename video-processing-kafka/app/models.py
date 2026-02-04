from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db import Base


class VideoProcessing(Base):
    __tablename__ = "video_processing"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String(64), unique=True, index=True, nullable=False)
    filename = Column(String(256), nullable=False)
    file_path = Column(String(512), nullable=False, default="")
    status = Column(String(32), default="queued", nullable=False)

    transcript = Column(Text, default="")
    summary = Column(Text, default="")
    bulletpoints = Column(Text, default="")
    action_items = Column(Text, default="")
    translation = Column(Text, default="")
    thumbnail_path = Column(String(512), default="")
    trace_id = Column(String(64), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
