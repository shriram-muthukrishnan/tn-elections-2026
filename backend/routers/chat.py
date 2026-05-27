import os, re, json, time, logging
from collections import defaultdict, deque
from difflib import get_close_matches
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from openai import AzureOpenAI

from database import get_db
from models import Party, Constituency, Result, PartySummary, CandidateProfile
from prompts import SYSTEM_PROMPT, USER_ENVELOPE, EXTRACTOR_SYSTEM_PROMPT
import stats
from candidate_query import TOOL_SPEC as CANDIDATE_QUERY_TOOL, run_query as run_candidate_query

router = APIRouter(tags=["Chat"])
log = logging.getLogger("chat")

# ---------- Azure OpenAI client (lazy) ----------
_client: Optional[AzureOpenAI] = None
def _azure_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key        = os.environ["AZURE_OPENAI_API_KEY"],
            api_version    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
    return _client

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
# Optional override: point to a cheaper/faster model for entity extraction.
# Falls back to the main DEPLOYMENT if not set.
EXTRACTOR_DEPLOYMENT = os.getenv("AZURE_OPENAI_EXTRACTOR_DEPLOYMENT", DEPLOYMENT)

# ---------- Schemas ----------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)

class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(min_length=1, max_length=10)
    constituency_no: Optional[int] = None
    party_abbr: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    context_used: dict
    model: str
    usage: dict

# ---------- Rate limit (in-memory, per process) ----------
_HITS: dict[str, deque] = defaultdict(deque)
_WINDOW_S, _MAX = 300, 20
def _rate_limit(ip: str):
    now = time.time()
    dq = _HITS[ip]
    while dq and now - dq[0] > _WINDOW_S:
        dq.popleft()
    if len(dq) >= _MAX:
        raise HTTPException(429, "Rate limit exceeded. Try again in a few minutes.")
    dq.append(now)

# ---------- Entity-extraction indexes (built once per process) ----------
# Constituency/candidate keys are normalized: lowercase, non-alphanumerics stripped.
# So DB "Coimbatore(South)" and user "Coimbatore South" both become "coimbatoresouth".
_CONST_INDEX: Optional[dict[str, int]] = None
_PARTY_SET: Optional[set[str]] = None
# Candidate name tokens (length >= 5) -> dict of const_no -> is_winner.
# is_winner is used as a tiebreaker when a token (e.g. "stalin") appears in
# multiple constituencies' candidate lists.
_CANDIDATE_TOKEN_INDEX: Optional[dict[str, dict[int, bool]]] = None
_MIN_CAND_TOKEN_LEN = 5
_MAX_CAND_HITS = 3
# A token that appears in more candidates than this is treated as noise
# (e.g. "kumar" appearing across dozens of candidates).
_AMBIGUOUS_TOKEN_LIMIT = 15

_NORM_RE = re.compile(r"[^a-z0-9]+")
_TOKEN_RE = re.compile(r"[a-z]+")
def _norm(s: str) -> str:
    return _NORM_RE.sub("", s.lower())

def warm_indexes(db: Session) -> None:
    """Called once at app startup from main.py lifespan."""
    global _CONST_INDEX, _PARTY_SET, _CANDIDATE_TOKEN_INDEX
    _CONST_INDEX = {
        _norm(name): const_no
        for name, const_no in db.query(Constituency.name, Constituency.const_no)
        if name
    }
    _PARTY_SET = {
        abbr for (abbr,) in db.query(Party.abbreviation) if abbr
    }
    cand_index: dict[str, dict[int, bool]] = defaultdict(dict)
    rows = (
        db.query(Result.candidate_name, Result.is_winner, Constituency.const_no)
        .join(Constituency, Result.constituency_id == Constituency.id)
        .all()
    )
    for name, is_winner, const_no in rows:
        if not name:
            continue
        for tok in _TOKEN_RE.findall(name.lower()):
            if len(tok) >= _MIN_CAND_TOKEN_LEN:
                # Keep the strongest evidence per (token, const_no): winner > loser.
                if not cand_index[tok].get(const_no):
                    cand_index[tok][const_no] = bool(is_winner)
    _CANDIDATE_TOKEN_INDEX = dict(cand_index)
    log.info("chat indexes warmed: %d constituencies, %d parties, %d candidate tokens",
             len(_CONST_INDEX), len(_PARTY_SET), len(_CANDIDATE_TOKEN_INDEX))

def _extract_entities(text: str) -> tuple[set[int], set[str]]:
    const_nos: set[int] = set()
    parties: set[str] = set()
    if _CONST_INDEX is None or _PARTY_SET is None or _CANDIDATE_TOKEN_INDEX is None:
        return const_nos, parties

    # Constituency numbers in the 1..234 range
    for m in re.findall(r"\b(\d{1,3})\b", text):
        n = int(m)
        if 1 <= n <= 234:
            const_nos.add(n)

    # Constituency names — normalize both sides, longest-first so
    # "coimbatoresouth" beats "coimbatore". Also scan alias-rewritten
    # variants of the text so nicknames ("tuticorin", "ooty", "tnagar")
    # surface their official-spelling counterparts without needing the LLM.
    normalized_text = _norm(text)
    search_texts = {normalized_text}
    for src, dst in _CONST_NAME_ALIASES:
        if src in normalized_text:
            search_texts.add(normalized_text.replace(src, dst))
    sorted_names = sorted(_CONST_INDEX, key=len, reverse=True)
    # Suppress overlapping shorter matches (e.g. "ATTUR" inside "AMBATTUR"):
    # mask each matched span so a shorter name can't re-match the same chars.
    for stext in search_texts:
        buf = list(stext)
        for name in sorted_names:
            if not name:
                continue
            joined = "".join(buf)
            idx = joined.find(name)
            if idx >= 0:
                const_nos.add(_CONST_INDEX[name])
                for i in range(idx, idx + len(name)):
                    buf[i] = " "

    # Candidate name tokens — e.g. "stalin", "palaniswami", "vijay".
    # Score each candidate by how many of the user's tokens hit their name,
    # then take the top matches. Lets "Muthuvel Karunanidhi Stalin" beat
    # plain "Stalin" when the user gives the fuller name, while a bare
    # "Stalin" still surfaces something useful.
    user_tokens = {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= _MIN_CAND_TOKEN_LEN}
    user_tokens -= _CAND_STOPWORDS
    # Score each candidate by token-hit count; tiebreak by is_winner.
    cand_score: dict[int, int] = defaultdict(int)
    cand_is_winner: dict[int, bool] = {}
    for tok in user_tokens:
        hits = _CANDIDATE_TOKEN_INDEX.get(tok)
        if not hits or len(hits) > _AMBIGUOUS_TOKEN_LIMIT:
            continue
        for cn, is_winner in hits.items():
            cand_score[cn] += 1
            if is_winner:
                cand_is_winner[cn] = True
    ranked = sorted(
        cand_score.items(),
        key=lambda kv: (-kv[1], not cand_is_winner.get(kv[0], False)),
    )
    for cn, _ in ranked[:_MAX_CAND_HITS]:
        const_nos.add(cn)

    # Party abbreviations as whole tokens (keep parens so "CPI(M)" survives)
    tokens = set(re.findall(r"[A-Za-z()]+", text.upper()))
    parties = {p for p in _PARTY_SET if p in tokens}

    return const_nos, parties

# Common English/Tamil filler words that aren't candidate-name signals.
_CAND_STOPWORDS = {
    "about", "after", "again", "alliance", "among", "assembly", "before", "below",
    "between", "candidate", "chief", "close", "constituency", "could", "district",
    "election", "first", "former", "history", "leader", "loses", "lost", "margin",
    "minister", "party", "performance", "results", "right", "score", "seats", "share",
    "should", "sitting", "south", "north", "east", "west", "central", "state",
    "tamil", "tamilnadu", "their", "there", "these", "those", "today", "total",
    "turnout", "under", "voter", "votes", "where", "which", "while", "would",
}

# ---------- LLM-based entity extraction (handles Tamil + English) ----------
def _llm_extract_entities(text: str) -> dict:
    """Ask the model to pull constituencies / candidates / parties from the
    user's message in their canonical English forms. Works for Tamil input.
    Returns {} on any failure so the caller can fall back to the regex extractor."""
    try:
        resp = _azure_client().chat.completions.create(
            model           = EXTRACTOR_DEPLOYMENT,
            messages        = [
                {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                {"role": "user",   "content": text},
            ],
            temperature     = 0,
            max_tokens      = 200,
            response_format = {"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        if not isinstance(data, dict):
            return {}
        return {
            "constituencies": [s for s in data.get("constituencies", []) if isinstance(s, str)],
            "candidates":     [s for s in data.get("candidates",     []) if isinstance(s, str)],
            "parties":        [s for s in data.get("parties",        []) if isinstance(s, str)],
        }
    except Exception:
        log.exception("LLM entity extraction failed; falling back to regex extractor")
        return {}

# Common nickname / colloquial spellings -> the spelling used in the DB names.
# Each entry produces an ADDITIONAL candidate key; the original is also tried.
# One-shot rewrites (no chaining), so adding more pairs is safe.
# Targets are normalized (lowercase, alphanumerics only) so they substring-match
# the DB names that have spaces / hyphens / dots (e.g. THIRU-VI-KA-NAGAR).
_CONST_NAME_ALIASES = [
    # Tiruchirappalli (#140 / #141)
    ("trichy",          "tiruchirappalli"),
    ("tiruchi",         "tiruchirappalli"),
    ("thiruchirapalli", "tiruchirappalli"),
    # Thoothukkudi / Tuticorin (#214)
    ("tuticorin",       "thoothukkudi"),
    ("tuticorn",        "thoothukkudi"),
    ("thoothukudi",     "thoothukkudi"),
    ("toothukudi",      "thoothukkudi"),
    # Kanniyakumari (#229)
    ("kanyakumari",     "kanniyakumari"),
    # Viluppuram (#74)
    ("villupuram",      "viluppuram"),
    # Tiruppattur (#50 Vellore, #185 Sivaganga — both DB spellings)
    ("tirupathur",      "tiruppattur"),
    ("thiruppathur",    "tiruppattur"),
    # Kancheepuram (#37)
    ("kanchipuram",     "kancheepuram"),
    # Tiruvallur (#4 THIRUVALLUR) and #185
    ("tiruvallur",      "thiruvallur"),
    # Tirunelveli (#224)
    ("nellai",          "tirunelveli"),
    ("thirunelveli",    "tirunelveli"),
    # Udhagamandalam / Ooty (#108)
    ("ooty",            "udhagamandalam"),
    ("ootacamund",      "udhagamandalam"),
    ("udagamandalam",   "udhagamandalam"),
    # Thanjavur (#174)
    ("tanjore",         "thanjavur"),
    ("tanjavur",        "thanjavur"),
    # Ramanathapuram (#211)
    ("ramnad",          "ramanathapuram"),
    ("ramnathapuram",   "ramanathapuram"),
    # Pudukkottai (#180)
    ("pudukottai",      "pudukkottai"),
    # Thiruvarur (#168)
    ("tiruvarur",       "thiruvarur"),
    # Sivaganga (#186)
    ("sivagangai",      "sivaganga"),
    # Nagapattinam (#163)
    ("nagapatnam",      "nagapattinam"),
    # Mayiladuthurai / Mayavaram (#161)
    ("mayavaram",       "mayiladuthurai"),
    # Tiruvannamalai (#63)
    ("thiruvannamalai", "tiruvannamalai"),
    # Tiruppur (#113 / #114)
    ("tirupur",         "tiruppur"),
    ("tirupoor",        "tiruppur"),
    # Mettuppalayam (#111)
    ("mettupalayam",    "mettuppalayam"),
    # Kovai / Coimbatore (#118 / #120)
    ("kovai",           "coimbatore"),
    ("covai",           "coimbatore"),
    # Chengalpattu (#32)
    ("chengalpet",      "chengalpattu"),
    ("chingleput",      "chengalpattu"),
    # Shozhinganallur (#27)
    ("sholinganallur",  "shozhinganallur"),
    ("solinganallur",   "shozhinganallur"),
    # Chepauk-Thiruvallikeni (#19, DB: CHEPAUK-THIRUVALLIKENI) — rewrite to
    # the full DB-normalized name so the substring scan picks up the seat.
    ("chepak",          "chepaukthiruvallikeni"),
    ("chepauk",         "chepaukthiruvallikeni"),
    ("triplicane",      "chepaukthiruvallikeni"),
    ("thiruvallikeni",  "chepaukthiruvallikeni"),
    # Thiyagarayanagar / T. Nagar (#24)
    ("tnagar",          "thiyagarayanagar"),
    ("thyagarayanagar", "thiyagarayanagar"),
    # Dr. Radhakrishnan Nagar / R.K. Nagar (#11)
    ("rknagar",         "drradhakrishnannagar"),
    ("radhakrishnannagar", "drradhakrishnannagar"),
    # Thiru-Vi-Ka Nagar / TVK Nagar (#15)
    ("tvknagar",        "thiruvikanagar"),
    # Madavaram (#9)
    ("madhavaram",      "madavaram"),
    # Ambattur (#8)
    ("ambathur",        "ambattur"),
    # Thiruvottiyur (#10)
    ("tiruvottiyur",    "thiruvottiyur"),
    ("tiruvotriyur",    "thiruvottiyur"),
    # Velachery (#26)
    ("velacheri",       "velachery"),
    # Nagercoil (#230)
    ("nagarcoil",       "nagercoil"),
    # Bodinayakanur (#200)
    ("bodinayakkanur",  "bodinayakanur"),
]

def _alias_variants(key: str) -> list[str]:
    """Return [key] plus any single-rewrite variants from the alias table.
    Variants are produced independently (no chaining) so they stay predictable."""
    variants = [key]
    for src, dst in _CONST_NAME_ALIASES:
        if src in key:
            variants.append(key.replace(src, dst))
    return variants


def _resolve_extracted(extracted: dict) -> tuple[set[int], set[str]]:
    """Resolve LLM-extracted English strings to const_nos and party abbreviations
    using the in-memory indexes built at startup."""
    const_nos: set[int] = set()
    parties: set[str] = set()
    if _CONST_INDEX is None or _PARTY_SET is None or _CANDIDATE_TOKEN_INDEX is None:
        return const_nos, parties

    # Constituencies: try numeric, then normalized exact match, then substring.
    for raw in extracted.get("constituencies", []):
        s = raw.strip()
        if s.isdigit():
            n = int(s)
            if 1 <= n <= 234:
                const_nos.add(n)
            continue
        key = _norm(s)
        if not key:
            continue
        matched = False
        for candidate_key in _alias_variants(key):
            if candidate_key in _CONST_INDEX:
                const_nos.add(_CONST_INDEX[candidate_key])
                matched = True
                break
        if matched:
            continue
        # Fallback 1: longest indexed name that is a substring of, or contains, any variant.
        for candidate_key in _alias_variants(key):
            hit = next(
                (name for name in sorted(_CONST_INDEX, key=len, reverse=True)
                 if name and (name in candidate_key or candidate_key in name)),
                None,
            )
            if hit:
                const_nos.add(_CONST_INDEX[hit])
                matched = True
                break
        if matched:
            continue
        # Fallback 2: fuzzy match against indexed names (handles typos like
        # "Kolatur" -> "Kolathur", "Coimbator" -> "Coimbatore"). Skip very
        # short keys to avoid spurious matches like "east" -> "Egmore".
        if len(key) >= 5:
            for candidate_key in _alias_variants(key):
                fuzzy = get_close_matches(candidate_key, _CONST_INDEX.keys(), n=1, cutoff=0.82)
                if fuzzy:
                    const_nos.add(_CONST_INDEX[fuzzy[0]])
                    break

    # Candidates: token-score against the candidate index; prefer winners on ties.
    for raw in extracted.get("candidates", []):
        tokens = {t for t in _TOKEN_RE.findall(raw.lower()) if len(t) >= _MIN_CAND_TOKEN_LEN}
        tokens -= _CAND_STOPWORDS
        score: dict[int, int] = defaultdict(int)
        is_winner_map: dict[int, bool] = {}
        for tok in tokens:
            hits = _CANDIDATE_TOKEN_INDEX.get(tok)
            if not hits or len(hits) > _AMBIGUOUS_TOKEN_LIMIT:
                continue
            for cn, is_winner in hits.items():
                score[cn] += 1
                if is_winner:
                    is_winner_map[cn] = True
        if score:
            best = sorted(
                score.items(),
                key=lambda kv: (-kv[1], not is_winner_map.get(kv[0], False)),
            )[0][0]
            const_nos.add(best)

    # Parties: exact uppercase match against known abbreviations.
    for raw in extracted.get("parties", []):
        abbr = raw.strip().upper()
        if abbr in _PARTY_SET:
            parties.add(abbr)

    return const_nos, parties

# ---------- DB fetchers ----------
# Keep only parties that won a seat OR contested broadly (>= 50 seats).
# Filters out long-tail fringe parties to save tokens and noise.
_SUMMARY_CONTESTED_THRESHOLD = 50

def _fmt_inr(n: Optional[int]) -> Optional[str]:
    """Indian-format rupee string: 12,34,56,789 -> '₹12.35 crore'."""
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

def _profile_dict(p: Optional[CandidateProfile]) -> Optional[dict]:
    if p is None:
        return None
    return {
        "age":               p.age,
        "gender":            p.gender,
        "education":         p.education,
        "profession_self":   p.profession_self,
        "profession_spouse": p.profession_spouse,
        "criminal_cases":    p.criminal_cases or 0,
        "criminal_details":  p.criminal_details,
        "total_assets":      p.total_assets,
        "total_liabilities": p.total_liabilities,
        "net_worth":         p.net_worth,
        "total_assets_display":      _fmt_inr(p.total_assets),
        "total_liabilities_display": _fmt_inr(p.total_liabilities),
        "net_worth_display":         _fmt_inr(p.net_worth),
        "source_url":        p.source_url,
    }

def _fetch_summary(db: Session) -> list[dict]:
    rows = (
        db.query(PartySummary)
        .options(joinedload(PartySummary.party))
        .order_by(PartySummary.seats_won.desc())
        .all()
    )
    out = []
    for ps in rows:
        seats = ps.seats_won or 0
        contested = ps.constituencies_contested or 0
        if seats == 0 and contested < _SUMMARY_CONTESTED_THRESHOLD:
            continue
        out.append({
            "party":       ps.party.abbreviation if ps.party else None,
            "party_full":  ps.party.full_name    if ps.party else None,
            "alliance":    ps.party.alliance     if ps.party else None,
            "seats_won":   seats,
            "vote_share":  float(ps.overall_vote_share) if ps.overall_vote_share is not None else None,
            "contested":   contested,
        })
    return out

def _fetch_constituency(db: Session, const_no: int) -> Optional[dict]:
    c = (
        db.query(Constituency)
        .options(joinedload(Constituency.winning_party))
        .filter(Constituency.const_no == const_no)
        .first()
    )
    if not c:
        return None
    results = (
        db.query(Result)
        .options(joinedload(Result.party), joinedload(Result.profile))
        .filter(Result.constituency_id == c.id)
        .order_by(Result.evm_votes.desc())
        .all()
    )
    return {
        "const_no":    c.const_no,
        "name":        c.name,
        "district":    c.district,
        "region":      c.region,
        "turnout_pct": float(c.voter_turnout_pct) if c.voter_turnout_pct is not None else None,
        "winner": {
            "candidate": c.winning_candidate,
            "party":     c.winning_party.abbreviation if c.winning_party else None,
            "margin":    c.winning_margin,
        },
        "candidates": [{
            "name":       r.candidate_name,
            "party":      r.party.abbreviation if r.party else ("NOTA" if r.is_nota else "IND"),
            "votes":      (r.evm_votes or 0) + (r.postal_votes or 0),
            "vote_share": float(r.vote_share_pct) if r.vote_share_pct is not None else None,
            "is_winner":  bool(r.is_winner),
            "profile":    _profile_dict(r.profile),
        } for r in results],
    }

def _fetch_party(db: Session, abbr: str) -> Optional[dict]:
    p = db.query(Party).filter(Party.abbreviation == abbr).first()
    if not p:
        return None
    summary = db.query(PartySummary).filter(PartySummary.party_id == p.id).first()
    top_wins = (
        db.query(Constituency)
        .filter(Constituency.winning_party_id == p.id)
        .order_by(Constituency.winning_margin.desc().nullslast())
        .limit(3)
        .all()
    )
    close_wins = (
        db.query(Constituency)
        .filter(Constituency.winning_party_id == p.id)
        .order_by(Constituency.winning_margin.asc().nullslast())
        .limit(3)
        .all()
    )
    return {
        "abbr":       p.abbreviation,
        "full_name":  p.full_name,
        "alliance":   p.alliance,
        "seats_won":  summary.seats_won if summary else 0,
        "vote_share": float(summary.overall_vote_share) if summary and summary.overall_vote_share is not None else None,
        "contested":  summary.constituencies_contested if summary else None,
        "top_wins":   [{"name": c.name, "candidate": c.winning_candidate, "margin": c.winning_margin} for c in top_wins],
        "close_wins": [{"name": c.name, "candidate": c.winning_candidate, "margin": c.winning_margin} for c in close_wins],
    }

def _build_context(db: Session, const_nos: set[int], parties: set[str]) -> dict:
    ctx: dict = {
        "summary": _fetch_summary(db),
        "stats":   stats.get_stats(),
    }
    if const_nos:
        rows = [_fetch_constituency(db, n) for n in list(const_nos)[:3]]
        ctx["constituencies"] = [r for r in rows if r is not None]
    if parties:
        rows = [_fetch_party(db, abbr) for abbr in list(parties)[:3]]
        ctx["parties"] = [r for r in rows if r is not None]
    return ctx

# ---------- Endpoint ----------
@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    _rate_limit(ip)

    last = req.messages[-1]
    if last.role != "user":
        raise HTTPException(400, "Last message must be from the user.")

    # LLM-based extractor handles Tamil + English + typos; regex extractor is
    # a cheap safety net for numeric constituency numbers and obvious matches.
    llm_entities = _llm_extract_entities(last.content)
    const_nos_llm, parties_llm = _resolve_extracted(llm_entities)
    const_nos_rx,  parties_rx  = _extract_entities(last.content)
    const_nos = const_nos_llm | const_nos_rx
    parties   = parties_llm   | parties_rx

    if req.constituency_no:
        const_nos.add(req.constituency_no)
    if req.party_abbr:
        parties.add(req.party_abbr.upper())

    context = _build_context(db, const_nos, parties)

    envelope = USER_ENVELOPE.format(
        context_json = json.dumps(context, ensure_ascii=False),
        user_message = last.content,
    )
    history = [{"role": m.role, "content": m.content} for m in req.messages[:-1]]
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": envelope}]
    )

    try:
        resp = _azure_client().chat.completions.create(
            model       = DEPLOYMENT,
            messages    = messages,
            temperature = 0.3,
            max_tokens  = 600,
            tools       = [CANDIDATE_QUERY_TOOL],
            tool_choice = "auto",
        )
    except Exception as e:
        log.exception("Azure OpenAI call failed")
        raise HTTPException(502, f"Upstream model error: {type(e).__name__}: {e}")

    # Tool-call loop: model may call query_candidates up to 3 times per turn.
    # Cap exists so a runaway tool-call doesn't blow latency/cost.
    tool_calls_used: list[dict] = []
    for _ in range(3):
        choice = resp.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            break
        # Append assistant turn carrying the tool_calls so the follow-up call
        # sees the conversation in valid OpenAI tool-call format.
        messages.append({
            "role": "assistant",
            "content": choice.message.content,
            "tool_calls": [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            if tc.function.name == "query_candidates":
                try:
                    result = run_candidate_query(db, args)
                except Exception as e:
                    log.exception("query_candidates failed")
                    result = {"error": f"{type(e).__name__}: {e}"}
                tool_calls_used.append({"args": args, "result_count": result.get("total_matching")})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            else:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"error": f"unknown tool {tc.function.name}"}),
                })
        try:
            resp = _azure_client().chat.completions.create(
                model       = DEPLOYMENT,
                messages    = messages,
                temperature = 0.3,
                max_tokens  = 600,
                tools       = [CANDIDATE_QUERY_TOOL],
                tool_choice = "auto",
            )
        except Exception as e:
            log.exception("Azure OpenAI follow-up call failed")
            raise HTTPException(502, f"Upstream model error: {type(e).__name__}: {e}")

    reply = resp.choices[0].message.content or ""
    usage = resp.usage.model_dump() if resp.usage else {}
    log.info("chat ok ip=%s tokens=%s entities=%s/%s tool_calls=%d",
             ip, usage.get("total_tokens"), len(const_nos), len(parties), len(tool_calls_used))

    return ChatResponse(
        reply        = reply,
        context_used = {**context, "tool_calls": tool_calls_used} if tool_calls_used else context,
        model        = DEPLOYMENT,
        usage        = usage,
    )
