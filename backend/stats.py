"""Precomputed aggregate stats for the chat assistant.

Computed once at app startup (from main.py lifespan) and injected into every
chat request as the "stats" block. Lets the model answer aggregation questions
(closest contest, highest turnout, regional breakdown, alliance totals, ...)
without routing each query shape to a separate fetcher.

If the data underneath changes (rare for finalized election results), restart
the app to recompute.
"""

import json
import logging
import os
import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from models import Party, Constituency, Result, PartySummary, CandidateProfile

log = logging.getLogger("stats")

# Cached on first call to warm_stats(); never mutated thereafter.
_STATS: Optional[dict] = None

# const_no -> district name (from geojson, since constituencies.district is NULL).
_AC_DISTRICT: dict[int, str] = {}

_GEOJSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "data", "tn_ac_2021.geojson",
)

# Strips trailing asterisks and collapses whitespace before lookup.
_DIST_CLEAN_RE = re.compile(r"[\s*]+")

def _clean_district(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _DIST_CLEAN_RE.sub(" ", name).strip().upper() or None


# District -> region mapping, keyed by the cleaned/uppercased district name as it
# appears in the geojson (which is from 2021, before later district splits).
DISTRICT_REGION = {
    # Chennai belt
    "CHENNAI":         "Chennai",
    "THIRUVALLUR":     "Chennai",
    "KANCHEEPURAM":    "Chennai",
    # Kongu (West)
    "COIMBATORE":      "Kongu",
    "TIRUPPUR":        "Kongu",
    "ERODE":           "Kongu",
    "SALEM":           "Kongu",
    "NAMAKKAL":        "Kongu",
    "KRISHNAGIRI":     "Kongu",
    "DHARMAPURI":      "Kongu",
    "THE NILGIRIS":    "Kongu",
    # Delta (Cauvery)
    "THANJAVUR":       "Delta",
    "THIRUVARUR":      "Delta",
    "NAGAPATTINAM":    "Delta",
    "CUDDALORE":       "Delta",
    "ARIYALUR":        "Delta",
    "PERAMBALUR":      "Delta",
    # Central
    "TIRUCHIRAPPALLI": "Central",
    "KARUR":           "Central",
    "PUDUKKOTTAI":     "Central",
    # South
    "MADURAI":         "South",
    "THENI":           "South",
    "DINDIGUL":        "South",
    "SIVAGANGA":       "South",
    "RAMANATHAPURAM":  "South",
    "VIRUDHUNAGAR":    "South",
    "TIRUNELVELI":     "South",
    "THOOTHUKKUDI":    "South",
    "KANNIYAKUMARI":   "South",
    # North
    "VELLORE":         "North",
    "TIRUVANNAMALAI":  "North",
    "VILUPPURAM":      "North",
}


def _load_ac_district_map() -> None:
    """Populate _AC_DISTRICT from the geojson. Safe to call multiple times."""
    if _AC_DISTRICT:
        return
    try:
        with open(_GEOJSON_PATH, encoding="utf-8") as f:
            geo = json.load(f)
        for feat in geo.get("features", []):
            props = feat.get("properties") or {}
            ac_no = props.get("AC_NO")
            dist  = _clean_district(props.get("DIST_NAME"))
            if ac_no is not None and dist:
                _AC_DISTRICT[int(ac_no)] = dist
    except FileNotFoundError:
        log.warning("geojson not found at %s; region/district stats will be empty", _GEOJSON_PATH)


def _district_for(c: Constituency) -> Optional[str]:
    # constituencies.district is NULL in the DB; geojson is the source of truth.
    return _AC_DISTRICT.get(c.const_no) if c.const_no is not None else None


def _region_for(district: Optional[str]) -> Optional[str]:
    cleaned = _clean_district(district)
    if not cleaned:
        return None
    return DISTRICT_REGION.get(cleaned)


def get_stats() -> dict:
    """Return the cached stats dict (empty if warm_stats has not run)."""
    return _STATS or {}


def _fmt_inr(n: Optional[int]) -> Optional[str]:
    """Indian-format rupee string for display in the chat context."""
    if n is None:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 10_000_000:
        return f"{sign}₹{n / 10_000_000:.2f} crore"
    if n >= 100_000:
        return f"{sign}₹{n / 100_000:.2f} lakh"
    if n >= 1_000:
        return f"{sign}₹{n / 1_000:.1f} thousand"
    return f"{sign}₹{n}"


def _compute_candidate_profile_stats(db: Session) -> dict:
    """State-wide aggregates from candidate_profiles. Joined to results when
    available (linked rows) so we can attribute by party / winner; otherwise
    counted in coverage and gender totals only.

    Kept intentionally minimal — only the questions that are asked constantly.
    Anything more specific (per-party crosstabs, age-bucketed strike rates,
    "richest BJP candidate in Kongu") goes through the query_candidates tool.
    """
    # Coverage: 3549 profiles total, ~3452 linked to a result row.
    total = db.query(func.count(CandidateProfile.id)).scalar() or 0
    linked = db.query(func.count(CandidateProfile.id)).filter(
        CandidateProfile.result_id.isnot(None)
    ).scalar() or 0

    # Gender split — from all 3549 profiles (gender is reliable regardless of linking).
    gender_rows = (
        db.query(CandidateProfile.gender, func.count(CandidateProfile.id))
        .group_by(CandidateProfile.gender)
        .all()
    )
    gender_counts = {g or "Unknown": n for g, n in gender_rows}
    male = gender_counts.get("Male", 0)
    female = gender_counts.get("Female", 0)
    gender_total = male + female

    # Linked-only rows (need result + party + constituency for the rest).
    linked_rows = (
        db.query(CandidateProfile, Result, Constituency, Party)
        .join(Result, Result.id == CandidateProfile.result_id)
        .join(Constituency, Constituency.id == Result.constituency_id)
        .outerjoin(Party, Party.id == Result.party_id)
        .all()
    )

    def label(p: CandidateProfile, r: Result, c: Constituency, party: Optional[Party]) -> dict:
        return {
            "name":         r.candidate_name,
            "constituency": c.name,
            "const_no":     c.const_no,
            "party":        party.abbreviation if party else ("IND" if r.is_independent else None),
            "is_winner":    bool(r.is_winner),
            "net_worth":    p.net_worth,
            "net_worth_display": _fmt_inr(p.net_worth),
            "age":          p.age,
            "criminal_cases": p.criminal_cases or 0,
        }

    # Criminal-case counts (overall + among winners).
    with_cases = [t for t in linked_rows if (t[0].criminal_cases or 0) > 0]
    winners_with_cases = [t for t in with_cases if t[1].is_winner]
    total_cases = sum((t[0].criminal_cases or 0) for t in linked_rows)

    # Wealth: top-10 richest overall, top-5 richest winners, top-5 poorest winners.
    with_nw = [t for t in linked_rows if t[0].net_worth is not None]
    top_richest = sorted(with_nw, key=lambda t: -(t[0].net_worth or 0))[:10]
    winner_nw = [t for t in with_nw if t[1].is_winner]
    top_richest_winners = sorted(winner_nw, key=lambda t: -(t[0].net_worth or 0))[:5]
    poorest_winners = sorted(winner_nw, key=lambda t: (t[0].net_worth or 0))[:5]
    crorepati_total = sum(1 for t in with_nw if (t[0].net_worth or 0) >= 10_000_000)
    crorepati_winners = sum(1 for t in winner_nw if (t[0].net_worth or 0) >= 10_000_000)

    # Most criminal cases — top 10 by raw count.
    top_criminal = sorted(
        [t for t in with_cases],
        key=lambda t: -(t[0].criminal_cases or 0),
    )[:10]

    # Women winners — direct list (small enough to ship in full).
    women_winners = [
        label(p, r, c, party)
        for p, r, c, party in linked_rows
        if r.is_winner and (p.gender or "").lower() == "female"
    ]
    women_winners.sort(key=lambda x: x["const_no"] or 0)

    return {
        "coverage": {
            "total_profiles": total,
            "linked_to_result": linked,
            "unlinked": total - linked,
            "note": "Some candidates from the results table do not have a profile (~3% unmatched). When a specific candidate's profile is not present, say so rather than guessing.",
        },
        "gender": {
            "male": male,
            "female": female,
            "women_pct_of_profiles": round(female * 100.0 / gender_total, 2) if gender_total else 0,
            "women_winners_count": len(women_winners),
            "women_winners": women_winners,
        },
        "criminal": {
            "candidates_with_cases": len(with_cases),
            "winners_with_cases": len(winners_with_cases),
            "winners_with_cases_pct": round(len(winners_with_cases) * 100.0 / max(1, sum(1 for t in linked_rows if t[1].is_winner)), 2),
            "total_cases_across_all_candidates": total_cases,
            "top_by_case_count": [label(p, r, c, party) for p, r, c, party in top_criminal],
        },
        "wealth": {
            "crorepati_candidates": crorepati_total,
            "crorepati_winners": crorepati_winners,
            "top_richest_candidates": [label(p, r, c, party) for p, r, c, party in top_richest],
            "top_richest_winners": [label(p, r, c, party) for p, r, c, party in top_richest_winners],
            "poorest_winners": [label(p, r, c, party) for p, r, c, party in poorest_winners],
        },
    }


def warm_stats(db: Session) -> None:
    """Compute all aggregates once. Idempotent: call again to refresh."""
    global _STATS
    _load_ac_district_map()
    s: dict = {}

    consts = (
        db.query(Constituency)
        .options(joinedload(Constituency.winning_party))
        .all()
    )

    def row(c: Constituency, **extra) -> dict:
        district = _district_for(c)
        return {
            "const_no":    c.const_no,
            "name":        c.name,
            "district":    district,
            "region":      _region_for(district),
            "winner":      c.winning_candidate,
            "party":       c.winning_party.abbreviation if c.winning_party else None,
            "margin":      c.winning_margin,
            "turnout_pct": float(c.voter_turnout_pct) if c.voter_turnout_pct is not None else None,
            **extra,
        }

    # --- Margin extremes ---
    with_margin = [c for c in consts if c.winning_margin is not None]
    s["closest_contests"] = [row(c) for c in sorted(with_margin, key=lambda c: c.winning_margin)[:10]]
    s["largest_margins"]  = [row(c) for c in sorted(with_margin, key=lambda c: -c.winning_margin)[:10]]

    # --- Turnout extremes ---
    with_turnout = [c for c in consts if c.voter_turnout_pct is not None]
    s["highest_turnout"] = [row(c) for c in sorted(with_turnout, key=lambda c: -float(c.voter_turnout_pct))[:10]]
    s["lowest_turnout"]  = [
        row(c) for c in sorted(
            [c for c in with_turnout if float(c.voter_turnout_pct) > 0],
            key=lambda c: float(c.voter_turnout_pct),
        )[:10]
    ]

    # --- Winner-level details (one query, reused) ---
    winner_rows = (
        db.query(Result, Constituency)
        .options(joinedload(Result.party))
        .join(Constituency, Result.constituency_id == Constituency.id)
        .filter(Result.is_winner == True)  # noqa: E712
        .all()
    )

    # Lowest winning vote share — narrow squeaks in multi-cornered fights.
    low_share = sorted(
        [(r, c) for r, c in winner_rows if r.vote_share_pct is not None],
        key=lambda rc: float(rc[0].vote_share_pct),
    )[:10]
    s["lowest_winning_vote_share"] = [
        row(c, winning_vote_share_pct=float(r.vote_share_pct)) for r, c in low_share
    ]

    # Highest individual vote totals.
    top_votes = sorted(
        winner_rows,
        key=lambda rc: -((rc[0].evm_votes or 0) + (rc[0].postal_votes or 0)),
    )[:10]
    s["highest_individual_votes"] = [
        row(c, votes=(r.evm_votes or 0) + (r.postal_votes or 0),
            vote_share_pct=float(r.vote_share_pct) if r.vote_share_pct is not None else None)
        for r, c in top_votes
    ]

    # --- NOTA-decided contests: NOTA votes > winning margin ---
    nota_rows = (
        db.query(Result, Constituency)
        .join(Constituency, Result.constituency_id == Constituency.id)
        .filter(Result.is_nota == True)  # noqa: E712
        .all()
    )
    nota_decided = []
    for r, c in nota_rows:
        nota_total = (r.evm_votes or 0) + (r.postal_votes or 0)
        if c.winning_margin is not None and nota_total > c.winning_margin:
            nota_decided.append(row(c, nota_votes=nota_total))
    nota_decided.sort(key=lambda x: -x["nota_votes"])
    s["nota_decided"] = nota_decided[:20]

    # --- Party-level summaries ---
    summaries = (
        db.query(PartySummary)
        .options(joinedload(PartySummary.party))
        .all()
    )
    s["party_strike_rate"] = sorted(
        [
            {
                "party":           ps.party.abbreviation if ps.party else None,
                "alliance":        ps.party.alliance if ps.party else None,
                "contested":       ps.constituencies_contested or 0,
                "won":             ps.seats_won or 0,
                "strike_rate_pct": round((ps.seats_won or 0) * 100.0 / ps.constituencies_contested, 1)
                                    if ps.constituencies_contested else 0,
            }
            for ps in summaries if ps.constituencies_contested
        ],
        key=lambda x: (-x["won"], -x["strike_rate_pct"]),
    )[:30]

    # --- State-level vote share, computed from results (party_summary's column is empty) ---
    total_state_votes = db.query(
        func.coalesce(func.sum(Result.evm_votes + Result.postal_votes), 0)
    ).scalar() or 0
    party_vote_rows = (
        db.query(
            Party.abbreviation,
            Party.alliance,
            func.coalesce(func.sum(Result.evm_votes + Result.postal_votes), 0).label("votes"),
        )
        .join(Result, Result.party_id == Party.id)
        .group_by(Party.id, Party.abbreviation, Party.alliance)
        .all()
    )
    state_vote_share = sorted(
        [
            {
                "party":          abbr,
                "alliance":       alliance,
                "votes":          int(votes),
                "vote_share_pct": round(int(votes) * 100.0 / total_state_votes, 2) if total_state_votes else 0,
            }
            for abbr, alliance, votes in party_vote_rows
        ],
        key=lambda x: -x["vote_share_pct"],
    )
    s["state_vote_share"] = state_vote_share[:30]

    # --- Alliance totals: seats + computed vote share ---
    seats_by_alliance: dict[str, int] = {}
    for ps in summaries:
        a = ps.party.alliance if ps.party else None
        if not a:
            continue
        seats_by_alliance[a] = seats_by_alliance.get(a, 0) + (ps.seats_won or 0)
    votes_by_alliance: dict[str, int] = {}
    for entry in state_vote_share:
        a = entry.get("alliance")
        if not a:
            continue
        votes_by_alliance[a] = votes_by_alliance.get(a, 0) + entry["votes"]
    s["alliance_totals"] = sorted(
        [
            {
                "alliance":       a,
                "seats":          seats,
                "vote_share_pct": round(votes_by_alliance.get(a, 0) * 100.0 / total_state_votes, 2)
                                    if total_state_votes else 0,
            }
            for a, seats in seats_by_alliance.items()
        ],
        key=lambda x: -x["seats"],
    )

    # --- Region breakdown: per-region wins + contested + strike rate per party ---
    region_won:       dict[str, dict[str, int]] = {}
    region_contested: dict[str, dict[str, int]] = {}
    for c in consts:
        region = _region_for(_district_for(c))
        if not region:
            continue
        if c.winning_party:
            abbr = c.winning_party.abbreviation
            region_won.setdefault(region, {})
            region_won[region][abbr] = region_won[region].get(abbr, 0) + 1

    contested_rows = (
        db.query(Party.abbreviation, Result.constituency_id, Constituency.const_no)
        .join(Result, Result.party_id == Party.id)
        .join(Constituency, Result.constituency_id == Constituency.id)
        .filter(Result.is_nota == False)  # noqa: E712
        .distinct()
        .all()
    )
    for abbr, _const_id, const_no in contested_rows:
        region = _region_for(_AC_DISTRICT.get(const_no))
        if not region or not abbr:
            continue
        region_contested.setdefault(region, {})
        region_contested[region][abbr] = region_contested[region].get(abbr, 0) + 1

    region_keys = set(region_won) | set(region_contested)

    # Per-region winner roster: every constituency in the region with its winner.
    region_winners: dict[str, list[dict]] = {}
    for c in consts:
        region = _region_for(_district_for(c))
        if not region:
            continue
        region_winners.setdefault(region, []).append({
            "const_no": c.const_no,
            "name":     c.name,
            "district": _district_for(c),
            "winner":   c.winning_candidate,
            "party":    c.winning_party.abbreviation if c.winning_party else None,
            "margin":   c.winning_margin,
        })
    for region in region_winners:
        region_winners[region].sort(key=lambda r: r["const_no"] or 0)

    s["regions"] = sorted(
        [
            {
                "region":      region,
                "total_seats": sum(region_won.get(region, {}).values()),
                "party_stats": sorted(
                    [
                        {
                            "party":           p,
                            "won":             won,
                            "contested":       contested,
                            "strike_rate_pct": round(won * 100.0 / contested, 1) if contested else 0,
                        }
                        for p in set(region_won.get(region, {})) | set(region_contested.get(region, {}))
                        for won, contested in [(
                            region_won.get(region, {}).get(p, 0),
                            region_contested.get(region, {}).get(p, 0),
                        )]
                        # Drop fringe parties so the payload stays compact.
                        if won >= 1 or contested >= 10
                    ],
                    key=lambda x: (-x["won"], -x["strike_rate_pct"]),
                )[:15],
                "constituencies": region_winners.get(region, []),
            }
            for region in region_keys
        ],
        key=lambda x: -x["total_seats"],
    )

    # --- District breakdown: same shape, smaller buckets ---
    district_party:   dict[str, dict[str, int]] = {}
    district_winners: dict[str, list[dict]]     = {}
    for c in consts:
        district = _district_for(c)
        if not district:
            continue
        d = district.title()
        if c.winning_party:
            abbr = c.winning_party.abbreviation
            district_party.setdefault(d, {})
            district_party[d][abbr] = district_party[d].get(abbr, 0) + 1
        district_winners.setdefault(d, []).append({
            "const_no": c.const_no,
            "name":     c.name,
            "winner":   c.winning_candidate,
            "party":    c.winning_party.abbreviation if c.winning_party else None,
            "margin":   c.winning_margin,
        })
    for d in district_winners:
        district_winners[d].sort(key=lambda r: r["const_no"] or 0)

    s["districts"] = sorted(
        [
            {
                "district":       d,
                "region":         _region_for(d),
                "total_seats":    sum(district_party.get(d, {}).values()),
                "party_seats":    sorted(
                    [{"party": p, "seats": n} for p, n in district_party.get(d, {}).items()],
                    key=lambda x: -x["seats"],
                ),
                "constituencies": district_winners.get(d, []),
            }
            for d in district_winners.keys()
        ],
        key=lambda x: (x.get("region") or "ZZ", -x["total_seats"]),
    )

    # --- Candidate-profile state-wide aggregates -----------------------------
    # Cheap, high-traffic answers: gender split, criminal-case counts, wealth
    # extremes. Anything more specific (filter by party + region + age range)
    # should go through the query_candidates tool, not be pre-computed here.
    s["candidate_profiles"] = _compute_candidate_profile_stats(db)

    _STATS = s
    log.info(
        "stats warmed: closest=%d turnout=%d regions=%d districts=%d alliances=%d state_total_votes=%s",
        len(s["closest_contests"]), len(s["highest_turnout"]),
        len(s["regions"]), len(s["districts"]), len(s["alliance_totals"]),
        total_state_votes,
    )
