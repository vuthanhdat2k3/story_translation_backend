"""Character Map API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.database import get_db
from app.models.character_map import CharacterMap
from app.models.novel import Novel
from app.schemas.character_map import (
    CharacterMapCreate,
    CharacterMapUpdate,
    CharacterMapResponse,
    CharacterMapListResponse,
)

router = APIRouter(prefix="/api", tags=["character-map"])


@router.get("/novels/{novel_id}/characters", response_model=CharacterMapListResponse)
def list_character_maps(novel_id: int, db: Session = Depends(get_db)):
    """List all character name mappings for a novel."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    maps = (
        db.query(CharacterMap)
        .filter(CharacterMap.novel_id == novel_id)
        .order_by(CharacterMap.cn_name)
        .all()
    )
    return CharacterMapListResponse(characters=maps, total=len(maps))


@router.post("/novels/{novel_id}/characters", response_model=CharacterMapResponse)
def create_character_map(
    novel_id: int,
    data: CharacterMapCreate,
    db: Session = Depends(get_db),
):
    """Add a new character name mapping."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    char_map = CharacterMap(
        novel_id=novel_id,
        cn_name=data.cn_name,
        vi_name=data.vi_name,
    )
    try:
        db.add(char_map)
        db.commit()
        db.refresh(char_map)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Character '{data.cn_name}' already exists for this novel",
        )
    return char_map


@router.put("/characters/{char_id}", response_model=CharacterMapResponse)
def update_character_map(
    char_id: int,
    data: CharacterMapUpdate,
    db: Session = Depends(get_db),
):
    """Update a character name mapping."""
    char_map = db.query(CharacterMap).filter(CharacterMap.id == char_id).first()
    if not char_map:
        raise HTTPException(status_code=404, detail="Character mapping not found")

    if data.cn_name is not None:
        char_map.cn_name = data.cn_name
    if data.vi_name is not None:
        char_map.vi_name = data.vi_name

    db.commit()
    db.refresh(char_map)
    return char_map


@router.delete("/characters/{char_id}")
def delete_character_map(char_id: int, db: Session = Depends(get_db)):
    """Delete a character name mapping."""
    char_map = db.query(CharacterMap).filter(CharacterMap.id == char_id).first()
    if not char_map:
        raise HTTPException(status_code=404, detail="Character mapping not found")

    db.delete(char_map)
    db.commit()
    return {"message": "Character mapping deleted successfully"}
