from pydantic import BaseModel


class VideoStatus(BaseModel):
    video_id: str
    status: str
    file_path: str
    transcript: str
    summary: str
    bulletpoints: str
    action_items: str
    translation: str
    thumbnail_path: str

    class Config:
        from_attributes = True
