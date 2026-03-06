from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CharacterMap(Base):
    __tablename__ = "character_maps"
    __table_args__ = (
        UniqueConstraint("novel_id", "cn_name", name="uq_novel_cn_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), nullable=False, index=True)
    cn_name: Mapped[str] = mapped_column(String(255), nullable=False)
    vi_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    novel = relationship("Novel", back_populates="character_maps")
