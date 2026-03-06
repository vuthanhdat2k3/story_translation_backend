"""Translation API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db, SessionLocal
from app.models.novel import Novel, NovelStatus
from app.models.chapter import Chapter, ChapterStatus
from app.services.translation_pipeline import (
    translate_novel as translate_novel_task,
    translate_chapter as translate_chapter_task,
)

router = APIRouter(prefix="/api/translate", tags=["translation"])


class TranslationStatusResponse(BaseModel):
    novel_id: int
    novel_title: str
    status: str
    total_chapters: int
    translated_chapters: int
    pending_chapters: int
    translating_chapters: int
    error_chapters: int


@router.post("/novel/{novel_id}")
def start_novel_translation(
    novel_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start translating all pending chapters of a novel in the background."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    if novel.status == NovelStatus.TRANSLATING:
        raise HTTPException(status_code=400, detail="Novel is already being translated")

    def _run_translation(nid: int):
        session = SessionLocal()
        try:
            translate_novel_task(session, nid)
        finally:
            session.close()

    background_tasks.add_task(_run_translation, novel_id)
    return {"message": f"Translation started for novel '{novel.title}'", "novel_id": novel_id}


@router.post("/chapter/{chapter_id}")
def start_chapter_translation(
    chapter_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Translate a single chapter in the background."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    if chapter.status == ChapterStatus.TRANSLATING:
        raise HTTPException(status_code=400, detail="Chapter is already being translated")

    def _run_translation(cid: int):
        session = SessionLocal()
        try:
            translate_chapter_task(session, cid)
        finally:
            session.close()

    background_tasks.add_task(_run_translation, chapter_id)
    return {"message": "Translation started", "chapter_id": chapter_id}


@router.post("/chapter/{chapter_id}/retranslate")
def retranslate_chapter(
    chapter_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Reset a chapter's translation and re-translate it from scratch."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    if chapter.status == ChapterStatus.TRANSLATING:
        raise HTTPException(status_code=400, detail="Chapter is already being translated")

    def _run_translation(cid: int):
        session = SessionLocal()
        try:
            translate_chapter_task(session, cid)
        finally:
            session.close()

    background_tasks.add_task(_run_translation, chapter_id)
    return {"message": "Re-translation started", "chapter_id": chapter_id}


@router.get("/status/{novel_id}", response_model=TranslationStatusResponse)
def get_translation_status(novel_id: int, db: Session = Depends(get_db)):
    """Get the translation status of a novel."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    pending = db.query(Chapter).filter(
        Chapter.novel_id == novel_id, Chapter.status == ChapterStatus.PENDING
    ).count()
    translating = db.query(Chapter).filter(
        Chapter.novel_id == novel_id, Chapter.status == ChapterStatus.TRANSLATING
    ).count()
    completed = db.query(Chapter).filter(
        Chapter.novel_id == novel_id, Chapter.status == ChapterStatus.COMPLETED
    ).count()
    error = db.query(Chapter).filter(
        Chapter.novel_id == novel_id, Chapter.status == ChapterStatus.ERROR
    ).count()

    return TranslationStatusResponse(
        novel_id=novel.id,
        novel_title=novel.title,
        status=novel.status.value,
        total_chapters=novel.total_chapters,
        translated_chapters=completed,
        pending_chapters=pending,
        translating_chapters=translating,
        error_chapters=error,
    )
