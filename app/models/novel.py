import enum
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class NovelStatus(str, enum.Enum):
    PENDING = "pending"
    TRANSLATING = "translating"
    COMPLETED = "completed"
    ERROR = "error"


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str] = mapped_column(String(255), default="Unknown")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[NovelStatus] = mapped_column(
        Enum(NovelStatus), default=NovelStatus.PENDING
    )
    total_chapters: Mapped[int] = mapped_column(default=0)
    translated_chapters: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")
    character_maps = relationship("CharacterMap", back_populates="novel", cascade="all, delete-orphan")
