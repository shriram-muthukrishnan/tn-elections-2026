from pydantic import BaseModel
from typing import Optional, List

# ── Constituency list (map layer) ─────────────────────────────
class ConstituencyMap(BaseModel):
    const_no:          int
    name:              str
    district:          Optional[str]
    winning_candidate: Optional[str]
    winning_margin:    Optional[int]
    total_votes_polled: Optional[int]
    winning_party:     Optional[str]   # abbreviation
    color_hex:         Optional[str]
    alliance:          Optional[str]

    class Config:
        from_attributes = True

# ── Candidate row inside constituency detail ──────────────────
class CandidateResult(BaseModel):
    candidate_name: str
    party_abbr:     Optional[str]
    party_full:     Optional[str]
    color_hex:      Optional[str]
    is_independent: bool
    is_nota:        bool
    is_winner:      bool
    evm_votes:      int
    postal_votes:   int
    total_votes:    int
    vote_share_pct: Optional[float]

    class Config:
        from_attributes = True

# ── Full constituency detail (side panel) ────────────────────
class ConstituencyDetail(BaseModel):
    const_no:           int
    name:               str
    district:           Optional[str]
    total_votes_polled: Optional[int]
    total_evm_votes:    Optional[int]
    total_postal_votes: Optional[int]
    winning_candidate:  Optional[str]
    winning_margin:     Optional[int]
    winning_party:      Optional[str]
    color_hex:          Optional[str]
    candidates:         List[CandidateResult]

    class Config:
        from_attributes = True

# ── Party summary ─────────────────────────────────────────────
class PartySummaryOut(BaseModel):
    abbreviation:            str
    full_name:               str
    color_hex:               str
    alliance:                Optional[str]
    seats_won:               int
    total_votes:             int
    overall_vote_share:      Optional[float]
    constituencies_contested: int

    class Config:
        from_attributes = True

# ── Party metadata ────────────────────────────────────────────
class PartyOut(BaseModel):
    id:           int
    abbreviation: str
    full_name:    str
    color_hex:    str
    alliance:     Optional[str]

    class Config:
        from_attributes = True

# ── Search result ─────────────────────────────────────────────
class SearchResult(BaseModel):
    const_no: int
    name:     str
    district: Optional[str]

    class Config:
        from_attributes = True
