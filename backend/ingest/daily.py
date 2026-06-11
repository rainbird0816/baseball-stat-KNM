"""당일 증분 수집 (Phase 8).

종료된 경기만 대상. 백필과 **동일한 game-level 수집기**를 날짜 범위만 좁혀 호출한다.
멱등 upsert 라 중복 실행해도 행이 늘지 않는다. 추후 cron/스케줄러로 일 1회 실행.

현재 game-level(T2) 수집기는 MLB StatsAPI 뿐이므로 daily 는 MLB 경기를 증분한다.
NPB/KBO 는 시즌(T1) 단위만 구현돼 있어 daily 대상이 아니다(전체 백필과 동일한 제약).

사용:
    python -m backend.ingest.daily --since 2022-04-16              # since~오늘
    python -m backend.ingest.daily --since 2022-04-16 --until 2022-04-18
"""
from __future__ import annotations

import argparse
from datetime import date

from backend.ingest.sources import mlb_statsapi


def run(since: str, until: str | None = None, db_path: str | None = None) -> None:
    """since~until(기본 오늘)의 종료된 MLB 경기를 멱등 증분 적재."""
    until = until or date.today().isoformat()
    print(f"[daily] MLB 종료 경기 증분 {since}..{until}")
    # backfill 은 Final 정규시즌 경기만 멱등 upsert. 해당 시즌 team_season 이
    # 적재돼 있어야 경기가 연결된다(미적재 시즌은 backfill 이 건너뜀).
    mlb_statsapi.backfill(since, until, db_path=db_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="daily")
    p.add_argument("--since", default=date.today().isoformat())
    p.add_argument("--until", default=None)
    p.add_argument("--db", default=None)
    a = p.parse_args()
    run(a.since, a.until, db_path=a.db)
