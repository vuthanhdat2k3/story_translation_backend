"""Novel API endpoints."""

import time
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import get_db
from app.models.novel import Novel, NovelStatus
from app.models.chapter import Chapter
from app.schemas.novel import NovelResponse, NovelListResponse, NovelCreate, NovelUpdate
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
from app.db.database import SessionLocal
from app.services.novel543_crawler import (
    crawl_latest_chapter_to_db,
    crawl_specific_chapter_to_db,
)
from app.services.translation_pipeline import translate_chapter as translate_chapter_task

class PasteChaptersRequest(BaseModel):
    text: str
    auto_translate: bool = False


class CrawlLatestRequest(BaseModel):
    source_url: str | None = None
    prefix: str | None = None
    pages_per_chapter: int | None = None
    auto_translate: bool = True
    cookie: str | None = None


class CrawlSpecificRequest(BaseModel):
    chapter_number: int
    source_url: str | None = None
    prefix: str | None = None
    pages_per_chapter: int | None = None
    auto_translate: bool = True


class CrawlRangeRequest(BaseModel):
    start_chapter: int
    end_chapter: int
    source_url: str | None = None
    prefix: str | None = None
    pages_per_chapter: int | None = None
    auto_translate: bool = True


def _normalize_source_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip()
    return normalized or None


def _normalize_prefix(prefix: str | None) -> str | None:
    if not prefix:
        return None
    normalized = prefix.strip()
    return normalized or None


def _normalize_pages_per_chapter(pages: int | None) -> int | None:
    if pages is None:
        return None
    return max(1, pages)

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
        source_url=_normalize_source_url(novel_in.source_url),
        crawl_prefix=_normalize_prefix(novel_in.crawl_prefix),
        pages_per_chapter=_normalize_pages_per_chapter(novel_in.pages_per_chapter) or 2,
        total_chapters=0,
        status=NovelStatus.PENDING,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    _invalidate_novels_cache()
    return novel


@router.put("/{novel_id}", response_model=NovelResponse)
def update_novel(
    novel_id: int,
    novel_in: NovelUpdate,
    db: Session = Depends(get_db),
):
    """Update novel metadata including per-novel crawl URL."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    if novel_in.title is not None:
        novel.title = novel_in.title
    if novel_in.author is not None:
        novel.author = novel_in.author
    if novel_in.description is not None:
        novel.description = novel_in.description
    if novel_in.source_url is not None:
        novel.source_url = _normalize_source_url(novel_in.source_url)
    if novel_in.crawl_prefix is not None:
        novel.crawl_prefix = _normalize_prefix(novel_in.crawl_prefix)
    if novel_in.pages_per_chapter is not None:
        novel.pages_per_chapter = _normalize_pages_per_chapter(novel_in.pages_per_chapter) or 1

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


@router.post("/{novel_id}/chapters/crawl-latest")
def crawl_latest_chapter(
    novel_id: int,
    req: CrawlLatestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Detect the latest chapter from novel543, save it, and optionally translate it."""
    try:
        result = crawl_latest_chapter_to_db(
            db,
            novel_id,
            _normalize_source_url(req.source_url),
            _normalize_prefix(req.prefix),
            _normalize_pages_per_chapter(req.pages_per_chapter),
            cookie_header=req.cookie,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl failed: {e}")

    if req.auto_translate:
        def _run_translation(chapter_id: int):
            session = SessionLocal()
            try:
                translate_chapter_task(session, chapter_id)
            finally:
                session.close()

        background_tasks.add_task(_run_translation, result.chapter_id)

    return {
        "message": "Crawl latest chapter thanh cong",
        "novel_id": novel_id,
        "chapter_id": result.chapter_id,
        "chapter_number": result.chapter_number,
        "title": result.title,
        "created": result.created,
        "translation_started": req.auto_translate,
    }


@router.post("/{novel_id}/chapters/crawl-specific")
def crawl_specific_chapter(
    novel_id: int,
    req: CrawlSpecificRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Crawl a specific chapter number from novel543, save it, and optionally translate it."""
    if req.chapter_number < 1:
        raise HTTPException(status_code=400, detail="So chuong khong hop le")

    try:
        result = crawl_specific_chapter_to_db(
            db,
            novel_id,
            req.chapter_number,
            _normalize_source_url(req.source_url),
            _normalize_prefix(req.prefix),
            _normalize_pages_per_chapter(req.pages_per_chapter),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl failed: {e}")

    if req.auto_translate:
        def _run_translation(chapter_id: int):
            session = SessionLocal()
            try:
                translate_chapter_task(session, chapter_id)
            finally:
                session.close()

        background_tasks.add_task(_run_translation, result.chapter_id)

    return {
        "message": f"Crawl chapter {req.chapter_number} thanh cong",
        "novel_id": novel_id,
        "chapter_id": result.chapter_id,
        "chapter_number": result.chapter_number,
        "title": result.title,
        "created": result.created,
        "translation_started": req.auto_translate,
    }


@router.post("/{novel_id}/chapters/crawl-range")
def crawl_chapter_range(
    novel_id: int,
    req: CrawlRangeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Crawl a range of chapter numbers and return a summary."""
    if req.start_chapter < 1 or req.end_chapter < 1:
        raise HTTPException(status_code=400, detail="So chuong khong hop le")
    if req.start_chapter > req.end_chapter:
        raise HTTPException(status_code=400, detail="start_chapter phai <= end_chapter")

    normalized_source_url = _normalize_source_url(req.source_url)
    normalized_prefix = _normalize_prefix(req.prefix)
    normalized_pages_per_chapter = _normalize_pages_per_chapter(req.pages_per_chapter)

    results: list[dict] = []
    success_count = 0
    failed_count = 0

    for chapter_number in range(req.start_chapter, req.end_chapter + 1):
        try:
            result = crawl_specific_chapter_to_db(
                db,
                novel_id,
                chapter_number,
                normalized_source_url,
                normalized_prefix,
                normalized_pages_per_chapter,
            )
            success_count += 1
            results.append(
                {
                    "chapter_number": chapter_number,
                    "ok": True,
                    "chapter_id": result.chapter_id,
                    "created": result.created,
                    "title": result.title,
                }
            )

            if req.auto_translate:
                def _run_translation(chapter_id: int):
                    session = SessionLocal()
                    try:
                        translate_chapter_task(session, chapter_id)
                    finally:
                        session.close()

                background_tasks.add_task(_run_translation, result.chapter_id)
        except Exception as e:
            failed_count += 1
            results.append(
                {
                    "chapter_number": chapter_number,
                    "ok": False,
                    "error": str(e),
                }
            )

    _invalidate_novels_cache()
    return {
        "message": f"Crawl range xong: {success_count} thanh cong, {failed_count} that bai",
        "novel_id": novel_id,
        "start_chapter": req.start_chapter,
        "end_chapter": req.end_chapter,
        "success_count": success_count,
        "failed_count": failed_count,
        "translation_started": req.auto_translate,
        "results": results,
    }
