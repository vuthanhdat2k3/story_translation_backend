"""Translation pipeline: chunking, translating, merging, and postprocessing."""

import logging
from sqlalchemy.orm import Session

from app.models.novel import Novel, NovelStatus
from app.models.chapter import Chapter, ChapterStatus
from app.models.character_map import CharacterMap
from app.services.gemini_service import translate_chunk, extract_character_names

logger = logging.getLogger(__name__)


def chunk_text(text: str, size: int = 1000) -> list[str]:
    """
    Split text into chunks of approximately `size` characters.
    Tries to split at paragraph boundaries to keep context intact.
    """
    if len(text) <= size:
        return [text]

    chunks = []
    paragraphs = text.split("\n")
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 1 > size and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += ("\n" if current_chunk else "") + para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def get_character_dict(db: Session, novel_id: int) -> dict[str, str]:
    """Get the character name mapping dict for a novel."""
    maps = db.query(CharacterMap).filter(CharacterMap.novel_id == novel_id).all()
    return {m.cn_name: m.vi_name for m in maps}


def translate_chapter(db: Session, chapter_id: int) -> None:
    """Translate a single chapter, always replacing old content with new."""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        logger.error(f"Chapter {chapter_id} not found")
        return

    try:
        # Clear old translation and mark as translating — committed immediately
        # so any concurrent reader sees the chapter is being retranslated.
        chapter.content_vi = None
        chapter.status = ChapterStatus.TRANSLATING
        db.commit()

        # Get character name dictionary (loads from database)
        char_dict = get_character_dict(db, chapter.novel_id)

        # Chunk the Chinese content
        chunks = chunk_text(chapter.content_cn)
        logger.info(f"Chapter {chapter_id}: split into {len(chunks)} chunks")

        # Translate each chunk
        translated_chunks = []
        new_title = None
        for i, chunk in enumerate(chunks):
            logger.info(f"Translating chunk {i + 1}/{len(chunks)} for chapter {chapter_id}")

            # Send title to translate for the first chunk only
            title_to_translate = chapter.title if i == 0 else None
            result = translate_chunk(chunk, title_to_translate, char_dict)

            translated_chunks.append(result.get("translation", ""))

            # Capture translated title (applied after all chunks done to avoid rollback loss)
            if i == 0 and result.get("translated_title"):
                new_title = result.get("translated_title")

            # Handle new characters that the LLM discovered
            new_chars = result.get("new_characters", {})
            if new_chars:
                for cn_name, vi_name in new_chars.items():
                    if cn_name not in char_dict:
                        char_dict[cn_name] = vi_name
                        from sqlalchemy.exc import IntegrityError
                        new_char_map = CharacterMap(
                            novel_id=chapter.novel_id,
                            cn_name=cn_name,
                            vi_name=vi_name,
                        )
                        try:
                            db.add(new_char_map)
                            db.commit()
                        except IntegrityError:
                            db.rollback()

        # --- Save new translation ---
        # Re-fetch the chapter in case the session was reset by a rollback above
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        chapter.content_vi = "\n\n".join(translated_chunks)
        if new_title:
            chapter.title = new_title
        db.commit()  # Commit content first to ensure it's persisted

        chapter.status = ChapterStatus.COMPLETED
        db.commit()

        # Update novel translated count
        novel = db.query(Novel).filter(Novel.id == chapter.novel_id).first()
        if novel:
            completed = (
                db.query(Chapter)
                .filter(
                    Chapter.novel_id == novel.id,
                    Chapter.status == ChapterStatus.COMPLETED,
                )
                .count()
            )
            novel.translated_chapters = completed
            db.commit()

        logger.info(f"Chapter {chapter_id} translated successfully")

    except Exception as e:
        logger.error(f"Error translating chapter {chapter_id}: {e}")
        try:
            chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
            if chapter:
                chapter.status = ChapterStatus.ERROR
                db.commit()
        except Exception:
            db.rollback()
        raise


def translate_novel(db: Session, novel_id: int) -> None:
    """Translate all pending chapters of a novel (background task)."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        logger.error(f"Novel {novel_id} not found")
        return

    try:
        novel.status = NovelStatus.TRANSLATING
        db.commit()

        # Auto-extract character names from first chapter if none exist
        existing_chars = (
            db.query(CharacterMap).filter(CharacterMap.novel_id == novel_id).count()
        )
        if existing_chars == 0:
            first_chapter = (
                db.query(Chapter)
                .filter(Chapter.novel_id == novel_id)
                .order_by(Chapter.chapter_number)
                .first()
            )
            if first_chapter:
                logger.info(f"Extracting character names for novel {novel_id}")
                names = extract_character_names(first_chapter.content_cn)
                for name_data in names:
                    char_map = CharacterMap(
                        novel_id=novel_id,
                        cn_name=name_data["cn_name"],
                        vi_name=name_data["vi_name"],
                    )
                    db.add(char_map)
                db.commit()

        # Translate all pending chapters
        chapters = (
            db.query(Chapter)
            .filter(
                Chapter.novel_id == novel_id,
                Chapter.status == ChapterStatus.PENDING,
            )
            .order_by(Chapter.chapter_number)
            .all()
        )

        for chapter in chapters:
            translate_chapter(db, chapter.id)

        novel.status = NovelStatus.COMPLETED
        db.commit()
        logger.info(f"Novel {novel_id} fully translated")

    except Exception as e:
        logger.error(f"Error translating novel {novel_id}: {e}")
        novel.status = NovelStatus.ERROR
        db.commit()
