import enum
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ChapterStatus(str, enum.Enum):
    PENDING = "pending"
    TRANSLATING = "translating"
    COMPLETED = "completed"
    ERROR = "error"


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="")
    content_cn: Mapped[str] = mapped_column(Text, nullable=False)
    content_vi: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ChapterStatus] = mapped_column(
        Enum(ChapterStatus), default=ChapterStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    novel = relationship("Novel", back_populates="chapters")
