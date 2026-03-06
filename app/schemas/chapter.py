from datetime import datetime
from pydantic import BaseModel
from app.models.chapter import ChapterStatus


class ChapterBase(BaseModel):
    chapter_number: int
    title: str = ""


class ChapterCreate(ChapterBase):
    content_cn: str


class ChapterResponse(ChapterBase):
    id: int
    novel_id: int
    content_cn: str
    content_vi: str | None = None
    status: ChapterStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChapterListItem(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    title: str
    status: ChapterStatus
    created_at: datetime

    class Config:
        from_attributes = True


class ChapterListResponse(BaseModel):
    chapters: list[ChapterListItem]
    total: int


class ChapterNavigation(BaseModel):
    current: ChapterResponse
    prev_id: int | None = None
    next_id: int | None = None
