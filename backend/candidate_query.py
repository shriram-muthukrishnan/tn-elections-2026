"""Constrained filter tool over candidate_profiles, exposed to the chat model
as an OpenAI tool call.

Why a constrained tool instead of raw SQL: the model picks filter values, but
the SQL stays in our code. That gives us a single place to enforce row limits,
sort whitelisting, normalization (e.g. NULL handling, party-abbr casing), and
audit logging — none of which we want to re-derive from a prompt every turn.
"""

from typing import Optional
from sqlalchemy import or_, func, case
from sqlalchemy.orm import Session, joinedload

from models import CandidateProfile, Result, Constituency, Party

MAX_LIMIT = 50
DEFAULT_LIMIT = 20

# Whitelisted sort keys -> (column, direction). Anything else -> default.
_SORT_KEYS = {
    "net_worth":         (CandidateProfile.net_worth, "desc"),
    "net_worth_asc":     (CandidateProfile.net_worth, "asc"),
    "criminal_cases":    (CandidateProfile.criminal_cases, "desc"),
    "age":               (CandidateProfile.age, "desc"),
    "age_asc":           (CandidateProfile.age, "asc"),
    "total_assets":      (CandidateProfile.total_assets, "desc"),
    "total_liabilities": (CandidateProfile.total_liabilities, "desc"),
}

# Whitelisted group_by keys -> SQL expression used for grouping + the label
# emitted in the result. Keep this small; the model can chain calls if needed.
_GROUP_KEYS = {
    "party":     Party.abbreviation,
    "region":    Constituency.region,
    "district":  Constituency.district,
    "gender":    CandidateProfile.gender,
    "is_winner": Result.is_winner,
    "education": CandidateProfile.education,
}

# JSON-schema spec sent to the model with every chat call.
TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "query_candidates",
        "description": (
            "Search candidate profiles from the 2026 Tamil Nadu Assembly election "
            "with filters. Use this for open-ended questions like 'women MLAs under 40', "
            "'crorepati candidates who lost', 'DMK candidates with criminal cases in Chennai', "
            "or 'top 10 richest BJP candidates'. Returns {total_matching, returned, "
            "truncated, candidates[]}: `total_matching` is the full count for "
            "'how many' questions (always quote this number, not `returned`); "
            "`candidates` is capped at 50. "
            "If you pass `group_by` (e.g. 'party', 'region', 'gender'), the response "
            "instead contains `groups: [{key, count, avg_net_worth, total_criminal_cases}]` "
            "with all filters applied first — use this for questions like "
            "'which party has the most women candidates' (filters: gender=Female, "
            "group_by=party) or 'criminal cases by region' (filters: has_criminal_cases=true, "
            "group_by=region). Combine multiple filters freely. Only the linked subset "
            "(~3452 of 3549 candidates) is searchable — a few are missing profile data."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "party":              {"type": "string", "description": "Party abbreviation (DMK, ADMK, BJP, INC, TVK, PMK, VCK, CPI, 'CPI(M)', IUML, NTK, BSP, DMDK, AMMK). Use 'IND' for independents."},
                "gender":             {"type": "string", "enum": ["Male", "Female"]},
                "min_age":            {"type": "integer"},
                "max_age":            {"type": "integer"},
                "min_net_worth":      {"type": "integer", "description": "Minimum net worth in rupees (1 crore = 10000000)."},
                "max_net_worth":      {"type": "integer", "description": "Maximum net worth in rupees."},
                "has_criminal_cases": {"type": "boolean", "description": "True = at least one criminal case; False = zero cases."},
                "min_criminal_cases": {"type": "integer"},
                "is_winner":          {"type": "boolean", "description": "True = MLA (winner only); False = lost."},
                "region":             {"type": "string", "description": "One of: Chennai, Kongu, Delta, Central, South, North."},
                "district":           {"type": "string", "description": "District name (matches case-insensitively)."},
                "constituency":       {"type": "string", "description": "Constituency name (matches case-insensitively)."},
                "education_contains": {"type": "string", "description": "Substring match on the free-text education field, e.g. 'graduate', 'doctorate', '12th'."},
                "profession_contains":{"type": "string", "description": "Substring match on the free-text profession field, e.g. 'lawyer', 'doctor', 'agriculture', 'business'."},
                "group_by":           {"type": "string", "enum": list(_GROUP_KEYS.keys()), "description": "Group results and return per-group counts + averages instead of a candidate list. Use for 'X by party / region / gender' questions."},
                "sort_by":            {"type": "string", "enum": list(_SORT_KEYS.keys()), "description": "Sort order for the candidate list. Ignored when group_by is set (groups are always sorted by count desc). Default 'net_worth'."},
                "limit":              {"type": "integer", "description": f"Max results (1..{MAX_LIMIT}). Default {DEFAULT_LIMIT}."},
            },
        },
    },
}


def _fmt_inr(n):
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


def run_query(db: Session, args: dict) -> dict:
    """Execute the filtered query and return a JSON-ready dict.

    Always returns {"count": N, "candidates": [...]} so the tool result shape
    is predictable for the model.
    """
    q = (
        db.query(CandidateProfile, Result, Constituency, Party)
        .join(Result, Result.id == CandidateProfile.result_id)
        .join(Constituency, Constituency.id == Result.constituency_id)
        .outerjoin(Party, Party.id == Result.party_id)
    )

    party = (args.get("party") or "").strip().upper() or None
    if party == "IND":
        q = q.filter(Result.is_independent == True)  # noqa: E712
    elif party:
        q = q.filter(Party.abbreviation == party)

    gender = args.get("gender")
    if gender in ("Male", "Female"):
        q = q.filter(CandidateProfile.gender == gender)

    if (v := args.get("min_age")) is not None:
        q = q.filter(CandidateProfile.age >= int(v))
    if (v := args.get("max_age")) is not None:
        q = q.filter(CandidateProfile.age <= int(v))

    if (v := args.get("min_net_worth")) is not None:
        q = q.filter(CandidateProfile.net_worth >= int(v))
    if (v := args.get("max_net_worth")) is not None:
        q = q.filter(CandidateProfile.net_worth <= int(v))

    has_cases = args.get("has_criminal_cases")
    if has_cases is True:
        q = q.filter(CandidateProfile.criminal_cases > 0)
    elif has_cases is False:
        q = q.filter(or_(CandidateProfile.criminal_cases == 0, CandidateProfile.criminal_cases.is_(None)))
    if (v := args.get("min_criminal_cases")) is not None:
        q = q.filter(CandidateProfile.criminal_cases >= int(v))

    is_winner = args.get("is_winner")
    if is_winner is True:
        q = q.filter(Result.is_winner == True)  # noqa: E712
    elif is_winner is False:
        q = q.filter(Result.is_winner == False)  # noqa: E712

    if (v := args.get("region")):
        q = q.filter(Constituency.region.ilike(v))
    if (v := args.get("district")):
        q = q.filter(Constituency.district.ilike(v))
    if (v := args.get("constituency")):
        q = q.filter(Constituency.name.ilike(f"%{v}%"))

    if (v := args.get("education_contains")):
        q = q.filter(CandidateProfile.education.ilike(f"%{v}%"))
    if (v := args.get("profession_contains")):
        q = q.filter(or_(
            CandidateProfile.profession_self.ilike(f"%{v}%"),
            CandidateProfile.profession_spouse.ilike(f"%{v}%"),
        ))

    # ---- Aggregation path: return per-group counts instead of a candidate list.
    group_by = args.get("group_by")
    if group_by in _GROUP_KEYS:
        group_col = _GROUP_KEYS[group_by]
        agg_q = (
            q.with_entities(
                group_col.label("key"),
                func.count(CandidateProfile.id).label("count"),
                func.avg(CandidateProfile.net_worth).label("avg_net_worth"),
                func.coalesce(func.sum(CandidateProfile.criminal_cases), 0).label("total_criminal_cases"),
                func.coalesce(
                    func.sum(case((CandidateProfile.criminal_cases > 0, 1), else_=0)),
                    0,
                ).label("candidates_with_cases"),
            )
            .group_by(group_col)
            .order_by(func.count(CandidateProfile.id).desc())
        )
        groups = []
        for key, cnt, avg_nw, total_cases, with_cases in agg_q.all():
            # is_winner groups by True/False — emit human-readable labels.
            label = key
            if group_by == "is_winner":
                label = "Winners" if key else "Lost"
            avg_nw_int = int(avg_nw) if avg_nw is not None else None
            groups.append({
                "key": label,
                "count": int(cnt),
                "avg_net_worth": avg_nw_int,
                "avg_net_worth_display": _fmt_inr(avg_nw_int),
                "candidates_with_criminal_cases": int(with_cases),
                "total_criminal_cases": int(total_cases),
            })
        return {
            "group_by": group_by,
            "total_matching": sum(g["count"] for g in groups),
            "groups": groups,
        }

    # ---- Candidate-list path (default).
    sort_by = args.get("sort_by") or "net_worth"
    col, direction = _SORT_KEYS.get(sort_by, _SORT_KEYS["net_worth"])
    q = q.order_by(col.desc().nullslast() if direction == "desc" else col.asc().nullslast())

    limit = args.get("limit") or DEFAULT_LIMIT
    try:
        limit = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    rows = q.limit(limit).all()
    # Total count BEFORE limit, so "how many <filter>" questions are answerable
    # even when the returned subset is capped at MAX_LIMIT.
    total_matching = q.order_by(None).count()
    return {
        "total_matching": total_matching,
        "returned": len(rows),
        "limit": limit,
        "truncated": total_matching > len(rows),
        "candidates": [
            {
                "name":         r.candidate_name,
                "constituency": c.name,
                "const_no":     c.const_no,
                "district":     c.district,
                "region":       c.region,
                "party":        party.abbreviation if party else ("IND" if r.is_independent else None),
                "is_winner":    bool(r.is_winner),
                "age":          p.age,
                "gender":       p.gender,
                "education":    p.education,
                "profession":   p.profession_self,
                "criminal_cases": p.criminal_cases or 0,
                "total_assets": p.total_assets,
                "total_assets_display": _fmt_inr(p.total_assets),
                "total_liabilities": p.total_liabilities,
                "total_liabilities_display": _fmt_inr(p.total_liabilities),
                "net_worth":    p.net_worth,
                "net_worth_display": _fmt_inr(p.net_worth),
            }
            for p, r, c, party in rows
        ],
    }
