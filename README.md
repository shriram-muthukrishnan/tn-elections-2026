# Tamil Nadu Elections 2026

Interactive map of Tamil Nadu's 234 assembly constituencies — party-wise results, vote shares, per-constituency candidate breakdowns, and a built-in chat assistant.

**Live**: <https://tn-elections-2026.azurewebsites.net>

## Features

- **Statewide map.** Every constituency colored by its winning party — the full picture in one view.
- **Constituency drill-down.** Click any seat to open a side panel with the full candidate list, vote counts, vote shares, winning margin, and the winner highlighted.
- **Party explorer.** Header tally and legend show every party that won seats, with full name, alliance, and seat count.
- **Party filter.** Click a party chip to highlight only the seats it won; click again to clear.
- **Chat assistant.** Ask natural-language questions in English or Tamil — e.g. *"Who won Kolathur?"*, *"Compare DMK and TVK seat-wise"*, *"எடப்பாடியில் யார் வெற்றி பெற்றார்?"* — and get data-backed answers grounded in the live DB.

## Chat assistant

The `/api/chat` endpoint is a small RAG pipeline over the same Postgres dataset that powers the map.

**What it answers well**
- Per-seat lookups (winner, runner-up, vote share, margin) — including typos and nicknames (`Trichy East`, `Tuticorin`, `Ooty`, `R.K. Nagar`).
- Statewide superlatives — closest contests, largest margins, lowest winning share, seats decided by less than NOTA.
- Aggregations by **party** (strike rate, biggest wins), **alliance** (vote share split), **district**, and **region** (Chennai / Kongu / Delta / Central / South / North).
- Multilingual queries — Tamil questions get Tamil answers.
- Politely declines out-of-scope questions (2021 results, future predictions).

**How it works**
1. **Entity resolution** — a normalized substring index over the 234 seat names, a candidate-name token index, ~70 nickname/alias rewrites (e.g. `Trichy → Tiruchirappalli`, `Ooty → Udhagamandalam`), and a `difflib` fuzzy fallback for typos.
2. **LLM-assisted extractor** — an Azure OpenAI JSON-mode call pulls constituencies / candidates / parties from the user's message, including Tamil input. Resolver above turns those into `const_no`s.
3. **Context assembly** — for each query the assistant gets:
    - the resolved constituency rows (full candidate breakdown + winner + margin),
    - a precomputed **stats block** (warmed at startup) covering closest/widest margins, lowest winning shares, NOTA-decided seats, per-party strike rates, alliance totals, per-region and per-district winner rosters,
    - the statewide party summary.
4. **Answer generation** — a final Azure OpenAI call with a system prompt that enforces grounding (cite numbers, never invent), citation rules, and language mirroring.

**Models** — Azure OpenAI `gpt-4.1` deployment by default; an optional cheaper deployment can be set for the extractor step.

**Rate limit** — per-IP sliding-window cap built into the endpoint.

## Stack

- **Backend:** FastAPI, SQLAlchemy 2, PostgreSQL
- **Chat:** Azure OpenAI (`openai` SDK), `difflib` fuzzy matching
- **Frontend:** Vanilla JS (ES modules), D3.js v7
- **Geo:** GeoJSON of 2021 assembly constituency boundaries

## Run locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then edit values (see below)

uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000>.

The GeoJSON file is expected at `frontend/data/tn_ac_2021.geojson`. See `backend/.env.example` for the required environment variables.

## API

| Method | Path                              | Purpose                                   |
| ------ | --------------------------------- | ----------------------------------------- |
| GET    | `/api/constituencies`             | All 234 constituencies (map layer)        |
| GET    | `/api/constituencies/{const_no}`  | Full result for one constituency          |
| GET    | `/api/summary`                    | Party-wise seat tally                     |
| GET    | `/api/parties`                    | Party metadata                            |
| GET    | `/api/search?q=`                  | Fuzzy constituency-name search            |
| POST   | `/api/chat`                       | Chat assistant — `{messages: [{role, content}]}` → `{reply}` |

## Data

Constituency results sourced from the Election Commission of India (<https://results.eci.gov.in>).

## License

MIT
