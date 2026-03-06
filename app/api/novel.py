"""Novel API endpoints."""

import time
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import get_db
from app.models.novel import Novel, NovelStatus
from app.models.chapter import Chapter
from app.schemas.novel import NovelResponse, NovelListResponse, NovelCreate
from app.services.file_parser import parse_file, split_into_chapters
from app.services.translation_pipeline import translate_novel as translate_novel_task

router = APIRouter(prefix="/api/novels", tags=["novels"])

# Simple in-memory cache for novel list (TTL = 30 seconds)
_novels_cache: dict = {"data": None, "expires_at": 0.0}


def _invalidate_novels_cache():
    _novels_cache["data"] = None
    _novels_cache["expires_at"] = 0.0


@router.get("", response_model=NovelListResponse)
def list_novels(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    """List all novels with pagination."""
    cache_key = f"{skip}:{limit}"
    now = time.monotonic()
    if _novels_cache["data"] and _novels_cache["data"].get("key") == cache_key and now < _novels_cache["expires_at"]:
        return _novels_cache["data"]["value"]

    total = db.query(func.count(Novel.id)).scalar()
    novels = (
        db.query(Novel)
        .order_by(Novel.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    result = NovelListResponse(novels=novels, total=total)
    _novels_cache["data"] = {"key": cache_key, "value": result}
    _novels_cache["expires_at"] = now + 30.0
    return result


@router.get("/{novel_id}", response_model=NovelResponse)
def get_novel(novel_id: int, db: Session = Depends(get_db)):
    """Get a novel by ID."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    return novel


from pydantic import BaseModel

class PasteChaptersRequest(BaseModel):
    text: str
    auto_translate: bool = False

@router.post("", response_model=NovelResponse)
def create_novel(
    novel_in: NovelCreate,
    db: Session = Depends(get_db)
):
    """Create an empty novel entry."""
    novel = Novel(
        title=novel_in.title,
        author=novel_in.author,
        description=novel_in.description,
        total_chapters=0,
        status=NovelStatus.PENDING,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    _invalidate_novels_cache()
    return novel


def _process_and_save_chapters(
    novel_id: int, 
    raw_text: str, 
    auto_translate: bool, 
    db: Session, 
    background_tasks: BackgroundTasks
):
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    # Get current max chapter number to append correctly
    last_chapter = db.query(Chapter).filter(Chapter.novel_id == novel_id).order_by(Chapter.chapter_number.desc()).first()
    start_num = last_chapter.chapter_number if last_chapter else 0

    chapters_data = split_into_chapters(raw_text)

    for i, ch_data in enumerate(chapters_data):
        chapter = Chapter(
            novel_id=novel.id,
            chapter_number=start_num + i + 1,
            title=ch_data["title"],
            content_cn=ch_data["content"],
        )
        db.add(chapter)

    # Update total chapters count
    novel.total_chapters = novel.total_chapters + len(chapters_data)
    
    # Check if novel status should be updated
    if novel.status == NovelStatus.COMPLETED and len(chapters_data) > 0:
        novel.status = NovelStatus.PENDING
        
    db.commit()
    db.refresh(novel)
    _invalidate_novels_cache()

    # Start background translation if requested
    if auto_translate:
        from app.db.database import SessionLocal
        def _run_translation(nid: int):
            session = SessionLocal()
            try:
                translate_novel_task(session, nid)
            finally:
                session.close()
        background_tasks.add_task(_run_translation, novel.id)

    return novel


@router.post("/{novel_id}/chapters/upload", response_model=NovelResponse)
async def upload_chapters(
    novel_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    auto_translate: bool = Form(False),
    db: Session = Depends(get_db),
):
    """
    Upload a novel file (.txt or .docx) and append its chapters to the novel.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("txt", "docx"):
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file format: .{ext}. Supported: .txt, .docx"
        )

    content = await file.read()
    try:
        raw_text = parse_file(file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _process_and_save_chapters(novel_id, raw_text, auto_translate, db, background_tasks)


@router.post("/{novel_id}/chapters/paste", response_model=NovelResponse)
def paste_chapters(
    novel_id: int,
    req: PasteChaptersRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Append pasted raw text as chapters to the novel.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text provided")
        
    return _process_and_save_chapters(novel_id, req.text, req.auto_translate, db, background_tasks)


@router.delete("/{novel_id}")
def delete_novel(novel_id: int, db: Session = Depends(get_db)):
    """Delete a novel and all its chapters and character maps."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    
    db.delete(novel)
    db.commit()
    return {"message": f"Novel '{novel.title}' deleted successfully"}
