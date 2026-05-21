from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Party
from schemas import PartyOut

router = APIRouter(tags=["Parties"])


@router.get("/parties", response_model=List[PartyOut])
def get_parties(db: Session = Depends(get_db)):
    """All party metadata with colors — used to build legend."""
    rows = db.query(Party).order_by(Party.abbreviation).all()
    return [
        PartyOut(
            id           = p.id,
            abbreviation = p.abbreviation,
            full_name    = p.full_name,
            color_hex    = p.color_hex,
            alliance     = p.alliance,
        )
        for p in rows
    ]
