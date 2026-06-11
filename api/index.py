"""Vercel Python 서버리스 진입점 (ASGI).

Vercel 은 `api/index.py` 의 최상위 `app` 변수를 자동으로 함수 핸들러로 로드한다.
(별도 핸들러/빌드 설정 불필요 — FastAPI Preset)

프론트엔드는 모든 API 를 `/api/*` 로 호출한다(`frontend/src/api.js`, BASE="/api").
- 로컬 dev: Vite 프록시가 `/api` 를 떼고 `http://127.0.0.1:8000` 으로 보냄 → FastAPI 가 `/leagues` 매칭.
- Vercel: `vercel.json` 의 rewrite 가 `/api/(.*)` 를 이 함수로 보내지만 경로는 **그대로**
  `/api/leagues` 로 도착한다(rewrite 는 prefix 를 떼지 않음).

따라서 여기서는 실제 FastAPI 앱(`backend.app.main:app`)을 부모 ASGI 앱의 `/api` 아래에 마운트해
`/api/leagues` → (마운트) → FastAPI `/leagues` 로 매칭되게 한다. 백엔드 라우터 코드는 손대지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (이 파일은 <root>/api/index.py).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402

from backend.app.main import app as backend_app  # noqa: E402

# 부모 ASGI 앱: 모든 요청을 /api 아래의 백엔드로 마운트.
# (/api/leagues → backend /leagues, /api/health → backend /health 등)
app = FastAPI(title="baseball-archive (vercel)", docs_url=None, redoc_url=None)
app.mount("/api", backend_app)
