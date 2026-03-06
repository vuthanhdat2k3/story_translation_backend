"""Chapter API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.chapter import Chapter
from app.schemas.chapter import (
    ChapterResponse,
    ChapterListItem,
    ChapterListResponse,
    ChapterNavigation,
)

router = APIRouter(prefix="/api", tags=["chapters"])


@router.delete("/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, db: Session = Depends(get_db)):
    """Delete a chapter by ID."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    db.delete(chapter)
    db.commit()
    return {"message": "Chapter deleted"}


@router.get("/novels/{novel_id}/chapters", response_model=ChapterListResponse)
def list_chapters(novel_id: int, db: Session = Depends(get_db)):
    """List all chapters of a novel."""
    chapters = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_number)
        .all()
    )
    return ChapterListResponse(chapters=chapters, total=len(chapters))


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
def get_chapter(chapter_id: int, db: Session = Depends(get_db)):
    """Get a chapter by ID with full content."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


@router.get("/chapters/{chapter_id}/navigate", response_model=ChapterNavigation)
def navigate_chapter(chapter_id: int, db: Session = Depends(get_db)):
    """Get a chapter with prev/next navigation info."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Find previous chapter
    prev_chapter = (
        db.query(Chapter)
        .filter(
            Chapter.novel_id == chapter.novel_id,
            Chapter.chapter_number < chapter.chapter_number,
        )
        .order_by(Chapter.chapter_number.desc())
        .first()
    )

    # Find next chapter
    next_chapter = (
        db.query(Chapter)
        .filter(
            Chapter.novel_id == chapter.novel_id,
            Chapter.chapter_number > chapter.chapter_number,
        )
        .order_by(Chapter.chapter_number)
        .first()
    )

    return ChapterNavigation(
        current=chapter,
        prev_id=prev_chapter.id if prev_chapter else None,
        next_id=next_chapter.id if next_chapter else None,
    )
