"""FastAPI 엔트리.

실행:
    uvicorn backend.app.main:app --reload
"""
from fastapi import FastAPI

from .routers import (
    health, leagues, players, games, postseason, franchises, status,
)

app = FastAPI(title="baseball-archive", version="0.1.0")
app.include_router(health.router)
app.include_router(leagues.router)
app.include_router(players.router)
app.include_router(games.router)
app.include_router(postseason.router)
app.include_router(franchises.router)
app.include_router(status.router)


@app.get("/")
def root():
    return {"app": "baseball-archive", "docs": "/docs"}
