from datetime import datetime
from pydantic import BaseModel
from app.models.novel import NovelStatus


class NovelBase(BaseModel):
    title: str
    author: str = "Unknown"
    description: str | None = None


class NovelCreate(NovelBase):
    pass


class NovelUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    description: str | None = None


class NovelResponse(NovelBase):
    id: int
    status: NovelStatus
    total_chapters: int
    translated_chapters: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NovelListResponse(BaseModel):
    novels: list[NovelResponse]
    total: int
