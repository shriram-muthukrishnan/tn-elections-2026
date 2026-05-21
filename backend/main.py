from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from database import engine, Base
from routers import constituencies, summary, parties

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Tamil Nadu Elections 2026", version="1.0.0", lifespan=lifespan)

app.include_router(constituencies.router, prefix="/api")
app.include_router(summary.router,        prefix="/api")
app.include_router(parties.router,        prefix="/api")

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND, "css")),  name="css")
app.mount("/js",     StaticFiles(directory=os.path.join(FRONTEND, "js")),   name="js")
app.mount("/data",   StaticFiles(directory=os.path.join(FRONTEND, "data")), name="data")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    return FileResponse(os.path.join(FRONTEND, "index.html"))
