from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from database import get_db
from models import Constituency, Result
from schemas import ConstituencyMap, ConstituencyDetail, CandidateResult, SearchResult

router = APIRouter(tags=["Constituencies"])


@router.get("/constituencies", response_model=List[ConstituencyMap])
def get_all_constituencies(db: Session = Depends(get_db)):
    """All 234 constituencies with winner info — used for map coloring."""
    rows = (
        db.query(Constituency)
        .options(joinedload(Constituency.winning_party))
        .order_by(Constituency.const_no)
        .all()
    )
    out = []
    for c in rows:
        out.append(ConstituencyMap(
            const_no           = c.const_no,
            name               = c.name,
            district           = c.district,
            winning_candidate  = c.winning_candidate,
            winning_margin     = c.winning_margin,
            total_votes_polled = c.total_votes_polled,
            winning_party      = c.winning_party.abbreviation if c.winning_party else None,
            color_hex          = c.winning_party.color_hex    if c.winning_party else "#CCCCCC",
            alliance           = c.winning_party.alliance     if c.winning_party else None,
        ))
    return out


@router.get("/constituencies/{const_no}", response_model=ConstituencyDetail)
def get_constituency(const_no: int, db: Session = Depends(get_db)):
    """Full result for one constituency — used for side panel on click."""
    c = (
        db.query(Constituency)
        .options(joinedload(Constituency.winning_party))
        .filter(Constituency.const_no == const_no)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail=f"Constituency {const_no} not found")

    results = (
        db.query(Result)
        .options(joinedload(Result.party))
        .filter(Result.constituency_id == c.id)
        .order_by(Result.evm_votes.desc())
        .all()
    )

    candidates = []
    for r in results:
        candidates.append(CandidateResult(
            candidate_name = r.candidate_name,
            party_abbr     = r.party.abbreviation if r.party else ("NOTA" if r.is_nota else "IND"),
            party_full     = r.party.full_name    if r.party else ("None of the Above" if r.is_nota else "Independent"),
            color_hex      = r.party.color_hex    if r.party else "#AAAAAA",
            is_independent = r.is_independent,
            is_nota        = r.is_nota,
            is_winner      = r.is_winner,
            evm_votes      = r.evm_votes    or 0,
            postal_votes   = r.postal_votes or 0,
            total_votes    = (r.evm_votes or 0) + (r.postal_votes or 0),
            vote_share_pct = float(r.vote_share_pct) if r.vote_share_pct else None,
        ))

    return ConstituencyDetail(
        const_no           = c.const_no,
        name               = c.name,
        district           = c.district,
        total_votes_polled = c.total_votes_polled,
        total_evm_votes    = c.total_evm_votes,
        total_postal_votes = c.total_postal_votes,
        winning_candidate  = c.winning_candidate,
        winning_margin     = c.winning_margin,
        winning_party      = c.winning_party.abbreviation if c.winning_party else None,
        color_hex          = c.winning_party.color_hex    if c.winning_party else "#CCCCCC",
        candidates         = candidates,
    )


@router.get("/search", response_model=List[SearchResult])
def search_constituencies(q: str, db: Session = Depends(get_db)):
    """Fuzzy name search — for chat assistant use later."""
    rows = (
        db.query(Constituency)
        .filter(Constituency.name.ilike(f"%{q}%"))
        .order_by(Constituency.name)
        .limit(10)
        .all()
    )
    return [SearchResult(const_no=r.const_no, name=r.name, district=r.district) for r in rows]
