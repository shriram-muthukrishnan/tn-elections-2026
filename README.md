# Tamil Nadu Elections 2026

Interactive map of Tamil Nadu's 234 assembly constituencies — party-wise results, vote shares, and per-constituency candidate breakdowns.

**Live**: <https://REPLACE_WITH_YOUR_APP.azurewebsites.net>

## Features
- **See who won, at a glance.** Every constituency on the map is colored by its winning party, so you get the statewide picture in one view.
- **Drill into any constituency.** Click a constituency to open a side panel with the full candidate list, vote counts, vote shares, winning margin, and the winning candidate highlighted.
- **Explore each party.** The header tally and legend show every party that won seats, with its full name, alliance, and seat count.
- **Filter the map by party.** Click a party in the legend (or header chip) to highlight only the constituencies it won; click again to clear the filter.
- **Ask the elections assistant** *(coming soon)*. A built-in chat where you can ask natural-language questions like "Which districts did DMK sweep?" or "Who won Katpadi?" and get precise, data-backed answers.

## Stack
- FastAPI + SQLAlchemy (PostgreSQL)
- Vanilla JS (ES modules) + D3.js v7
- GeoJSON of 2021 assembly constituency boundaries

## Run locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then edit .env with your DATABASE_URL

uvicorn main:app --reload --port 8000
```
Open <http://localhost:8000>.

The GeoJSON file is expected at `frontend/data/tn_ac_2021.geojson`.

## API

| Method | Path                              | Purpose                                   |
| ------ | --------------------------------- | ----------------------------------------- |
| GET    | `/api/constituencies`             | All 234 constituencies (map layer)        |
| GET    | `/api/constituencies/{const_no}`  | Full result for one constituency          |
| GET    | `/api/summary`                    | Party-wise seat tally                     |
| GET    | `/api/parties`                    | Party metadata                            |
| GET    | `/api/search?q=`                  | Fuzzy constituency-name search            |

## Data
Constituency results sourced from the Election Commission of India (<https://results.eci.gov.in>).

## License
MIT


## Run locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then edit .env with your DATABASE_URL

uvicorn main:app --reload --port 8000
```
Open <http://localhost:8000>.

The GeoJSON file is expected at `frontend/data/tn_ac_2021.geojson`.

## API

| Method | Path                              | Purpose                                   |
| ------ | --------------------------------- | ----------------------------------------- |
| GET    | `/api/constituencies`             | All 234 constituencies (map layer)        |
| GET    | `/api/constituencies/{const_no}`  | Full result for one constituency          |
| GET    | `/api/summary`                    | Party-wise seat tally                     |
| GET    | `/api/parties`                    | Party metadata                            |
| GET    | `/api/search?q=`                  | Fuzzy constituency-name search            |

## Data
Constituency results sourced from the Election Commission of India (<https://results.eci.gov.in>).

## License
MIT
