from fastapi import APIRouter
from ..db import get_conn

router = APIRouter()


@router.get("/health")
def health():
    conn = get_conn()
    n = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    conn.close()
    return {"status": "ok", "tables": n}
