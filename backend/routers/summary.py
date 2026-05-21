from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List

from database import get_db
from models import Party, PartySummary
from schemas import PartySummaryOut

router = APIRouter(tags=["Summary"])


@router.get("/summary", response_model=List[PartySummaryOut])
def get_summary(db: Session = Depends(get_db)):
    """Party-wise seat tally and vote share — used for header chips and legend."""
    rows = (
        db.query(PartySummary)
        .options(joinedload(PartySummary.party))
        .join(Party, PartySummary.party_id == Party.id)
        .order_by(PartySummary.seats_won.desc())
        .all()
    )
    out = []
    for ps in rows:
        p = ps.party
        out.append(PartySummaryOut(
            abbreviation             = p.abbreviation,
            full_name                = p.full_name,
            color_hex                = p.color_hex,
            alliance                 = p.alliance,
            seats_won                = ps.seats_won               or 0,
            total_votes              = ps.total_votes              or 0,
            overall_vote_share       = float(ps.overall_vote_share) if ps.overall_vote_share else None,
            constituencies_contested = ps.constituencies_contested or 0,
        ))
    return out
