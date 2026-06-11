"""KBO 수집기 (Phase 3) — robots 준수 CSV 적재.

Statiz/KBO공식 사이트는 robots.txt 가 모든 봇(Claude 포함)을 차단하므로 크롤링하지
않는다. 대신 라이선스/이용약관상 사용 가능한 CSV 를 data/raw/kbo/ 에 두고 적재한다.
(자세한 형식은 data/raw/kbo/README.md)

inspect() 는 '원본을 컨텍스트에 넣지 않는다'는 원칙을 코드로 강제한다 —
컬럼명/shape/head 요약만 출력한다.

사용:
    python -m backend.ingest.sources.kbo_statiz inspect batting_2022.csv
    python -m backend.ingest.sources.kbo_statiz load --year 2022   # 매핑 확정 후
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "kbo"


def inspect(filename: str) -> None:
    """원본 CSV 요약만 출력 (전체 내용은 절대 출력하지 않음)."""
    import pandas as pd

    path = RAW / filename
    if not path.exists():
        raise SystemExit(
            f"{path} 없음. 라이선스 확인된 KBO CSV 를 data/raw/kbo/ 에 두세요 "
            f"(형식: data/raw/kbo/README.md)."
        )
    # 한글 인코딩(utf-8 / cp949) 자동 시도
    try:
        df = pd.read_csv(path)
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="cp949")
    print(f"[{filename}] shape={df.shape}")
    print("columns:", list(df.columns))
    print(df.head(3).to_string())


def load(year: int) -> None:
    """data/raw/kbo/ CSV → 코어 테이블 멱등 upsert. (CSV 컬럼 확인 후 구현)

    적재 순서: season → team_season(승/패/무) → person(한글+로마자) → stint →
    batting_season / pitching_season. 무승부 ties 반영, ip_outs 정수 환산,
    source provenance 기록.
    """
    raise NotImplementedError(
        "Phase 3: data/raw/kbo/ 의 CSV 컬럼을 inspect 로 확인한 뒤 "
        "backend/ingest/normalize/kbo_mapping.py 매핑을 채우고 적재 로직을 구현한다."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="kbo_statiz")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect")
    pi.add_argument("filename")
    pl = sub.add_parser("load")
    pl.add_argument("--year", type=int, required=True)
    a = p.parse_args()
    if a.cmd == "inspect":
        inspect(a.filename)
    else:
        load(a.year)
