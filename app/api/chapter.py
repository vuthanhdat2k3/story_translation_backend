"""Chapter API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, load_only

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
def list_chapters(
    novel_id: int,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """List chapters of a novel with pagination. Only metadata is returned (no content)."""
    query = (
        db.query(Chapter)
        .options(
            load_only(
                Chapter.id,
                Chapter.novel_id,
                Chapter.chapter_number,
                Chapter.title,
                Chapter.status,
                Chapter.created_at,
            )
        )
        .filter(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_number)
    )
    total = query.count()
    chapters = query.offset(skip).limit(limit).all()
    return ChapterListResponse(chapters=chapters, total=total)


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

    # Fetch prev and next IDs in a single query using subquery approach
    prev_next = (
        db.query(Chapter.id, Chapter.chapter_number)
        .filter(
            Chapter.novel_id == chapter.novel_id,
            Chapter.chapter_number.in_([
                db.query(Chapter.chapter_number)
                .filter(
                    Chapter.novel_id == chapter.novel_id,
                    Chapter.chapter_number < chapter.chapter_number,
                )
                .order_by(Chapter.chapter_number.desc())
                .limit(1)
                .scalar_subquery(),
                db.query(Chapter.chapter_number)
                .filter(
                    Chapter.novel_id == chapter.novel_id,
                    Chapter.chapter_number > chapter.chapter_number,
                )
                .order_by(Chapter.chapter_number)
                .limit(1)
                .scalar_subquery(),
            ]),
        )
        .all()
    )

    prev_id = None
    next_id = None
    for row_id, row_num in prev_next:
        if row_num < chapter.chapter_number:
            prev_id = row_id
        else:
            next_id = row_id

    return ChapterNavigation(
        current=chapter,
        prev_id=prev_id,
        next_id=next_id,
    )
