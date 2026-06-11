"""MLB 역대(deep history) 백필 — 역대 포스트시즌 + WS MVP 확대용.

표준 빌드(`init_db --fresh` + phase 테스트)는 슬라이스 시즌만 적재한다.
이 스크립트는 그 위에 **무거운 역대 백필**을 얹는다(opt-in):

  1. mlb_lahman.backfill_teams(start, end)      — season/franchise/team_season 만 가볍게(breadth)
  2. mlb_lahman.backfill_full(full_start, full_end) — WS MVP 시대 풀로드(person/stat, depth) [--no-full 로 생략]
  3. postseason.load()                           — 전 연도 SeriesPost + WS MVP(person 있는 연도)
  4. logos.load()                                — 새 역사적 프랜차이즈 로고 era 동기화

모두 멱등 — 재실행해도 행이 늘지 않는다. WS MVP 상은 Lahman 에 1955~2021 수록이라
풀로드 기본 범위를 그에 맞춘다(1994 는 파업으로 WS 없음).

사용:
    python scripts/backfill_mlb_history.py                  # team 1903~2022 + full 1955~2021
    python scripts/backfill_mlb_history.py --no-full        # team_season 만(가벼움)
    python scripts/backfill_mlb_history.py --full-start 1990
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `python scripts/backfill_mlb_history.py` 로 직접 실행해도 backend 패키지를 찾도록
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ingest.sources import logos, postseason  # noqa: E402
from backend.ingest.sources.mlb_lahman import (  # noqa: E402
    backfill_full,
    backfill_teams,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=1903)       # 1903 = 첫 월드시리즈
    p.add_argument("--end", type=int, default=2022)         # 공개 미러 최신 시즌
    p.add_argument("--full-start", type=int, default=1955)  # WS MVP 상 시작
    p.add_argument("--full-end", type=int, default=2021)    # WS MVP 상 마지막(미러)
    p.add_argument("--no-full", action="store_true", help="풀로드 생략(team_season 만)")
    a = p.parse_args()

    print(f"[1] MLB team_season 백필 {a.start}~{a.end} …")
    backfill_teams(a.start, a.end)
    if not a.no_full:
        print(f"[2] WS MVP 시대 풀로드 {a.full_start}~{a.full_end} (무거움) …")
        backfill_full(a.full_start, a.full_end)
    print("[3] 포스트시즌 적재(전 연도 + WS MVP) …")
    postseason.load()
    print("[4] 로고 era 동기화 …")
    logos.load()
    print("done.")


if __name__ == "__main__":
    main()
