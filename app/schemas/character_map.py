from datetime import datetime
from pydantic import BaseModel


class CharacterMapBase(BaseModel):
    cn_name: str
    vi_name: str


class CharacterMapCreate(CharacterMapBase):
    pass


class CharacterMapUpdate(BaseModel):
    cn_name: str | None = None
    vi_name: str | None = None


class CharacterMapResponse(CharacterMapBase):
    id: int
    novel_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CharacterMapListResponse(BaseModel):
    characters: list[CharacterMapResponse]
    total: int
