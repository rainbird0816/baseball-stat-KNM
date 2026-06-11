"""Phase 5 — 크로스리그 인물 매칭/병합.

NPB↔MLB / KBO↔MLB 등 리그를 이동한 동일인을 하나의 person 으로 통합한다.
NPB BIS / KBO 기록실 표에는 로마자·생일·공유ID 가 없어 자동 매칭이 불가능하므로
**큐레이션 크로스워크**(CROSSWALK)로 동일인을 명시한 뒤 병합한다.

식별 정책:
  - keep = MLB person. ('mlbam', id) 또는 ('lahman', playerID) external_id 로
    조회한다(이미 Lahman/StatsAPI 로 mlbam/bbref/lahman/retrosheet 가 묶여 있음).
  - drop = 같은 원어 이름(공백 정규화 후 일치) 을 가진
    **source IN ('npb','kbo') external_id 보유** person. keep_id 는 제외한다.
    (NPB=한자, KBO=한글 — 같은 native_name 필드로 매칭한다.)

병합(merge_persons):
  drop 을 참조하는 person FK 6곳을 keep 으로 repoint 후 drop person 삭제.
    person_external_id / stint / award_share /
    postseason_series.mvp_person_id / player_batting_game / player_pitching_game
  (batting/pitching/fielding_season 은 stint_id 로 매달리므로 stint repoint 로 따라온다.)
  원어 한자(name_native) 보존 + 기존 로마자(name_roman) 유지 정책.

멱등성:
  병합 후엔 그 원어 이름을 가진 npb/kbo-source person 이 keep 외에 없으므로,
  재실행 시 drop 후보가 0건 → merge 0건(person count 불변).

사용:
  python -m backend.ingest.normalize.person_match run
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "baseball.db"

# --------------------------------------------------------------------------- #
# 큐레이션 크로스워크
# --------------------------------------------------------------------------- #
# 각 항목:
#   canonical    : keep 으로 쓸 MLB external_id (source, external_id)
#   native_name  : 이동 리그(NPB=한자 / KBO=한글) 측 원어 이름(공백 무시 비교)
#   note         : 메모
# 데이터에 해당 NPB/KBO 시즌이 없으면(drop 후보 0건) 자동 no-op 으로 건너뛴다.
CROSSWALK: list[dict] = [
    {
        "canonical": ("mlbam", "673548"),
        "native_name": "鈴木誠也",
        "note": "Seiya Suzuki NPB Hiroshima(2021) → MLB Cubs(2022)",
    },
    # 확장 예시(데이터에 NPB 시즌 없으면 no-op):
    {
        "canonical": ("mlbam", "660271"),
        "native_name": "大谷翔平",
        "note": "Shohei Ohtani NPB Nippon-Ham → MLB Angels/Dodgers",
    },
    {
        "canonical": ("mlbam", "506433"),
        "native_name": "ダルビッシュ有",
        "note": "Yu Darvish NPB Nippon-Ham → MLB",
    },
    # ----- 확대 이동 선수 (canonical=('lahman', playerID): 역대 MLB person 은 mlbam 미보유) -----
    # 각 항목은 NPB person 이 실제 적재되고 한자(공백 정규화 후)가 일치할 때만 병합된다.
    # 필요한 NPB backfill 연도: 2006, 2010, 2011, 2013 (npb.jp BIS 는 2005+ 만 제공).
    {
        "canonical": ("lahman", "tanakma01"),
        "native_name": "田中将大",
        "note": "Masahiro Tanaka NPB Rakuten(2007-13) → MLB Yankees (NPB 2010/2011/2013)",
    },
    {
        "canonical": ("lahman", "maedake01"),
        "native_name": "前田健太",
        "note": "Kenta Maeda NPB Hiroshima(2008-15) → MLB Dodgers (NPB 2010/2011/2013)",
    },
    {
        "canonical": ("lahman", "fukudko01"),
        "native_name": "福留孝介",
        "note": "Kosuke Fukudome NPB Chunichi → MLB Cubs (NPB 2006)",
    },
    {
        "canonical": ("lahman", "darviyu01"),
        "native_name": "ダルビッシュ有",
        "note": "Yu Darvish NPB Nippon-Ham → MLB Rangers (NPB 2006/2010/2011)",
    },
    {
        "canonical": ("lahman", "kawasmu01"),
        "native_name": "川崎宗則",
        "note": "Munenori Kawasaki NPB SoftBank → MLB (NPB 2006/2010/2011)",
    },
    # Hideki Matsui(松井秀喜, NPB 2002) / Ichiro Suzuki(NPB 2000) 는 npb.jp BIS 가
    # 2005 미만 통계 페이지를 제공하지 않아(404) NPB person 부재 → 병합 불가(보류).
    #
    # ----- KBO↔MLB 이동 선수 (native_name=한글; KBO backfill 연도 명시) -----
    {
        "canonical": ("lahman", "ryuhy01"),
        "native_name": "류현진",
        "note": "Hyun Jin Ryu KBO 한화(2006-12) → MLB Dodgers/Blue Jays (KBO 2010)",
    },
    {
        "canonical": ("lahman", "kimha01"),
        "native_name": "김하성",
        "note": "Ha-Seong Kim KBO 키움/넥센(2014-20) → MLB Padres (KBO 2020)",
    },
    # 이정후(Jung Hoo Lee) KBO 키움(2017-23) → MLB Giants(2024).
    # MLB 2024 는 StatsAPI 시즌 스탯으로 적재 → mlbam person(id 808982) 생성됨.
    # canonical=mlbam 이어야 그 새 MLB person 을 keep 으로 잡아 KBO person 을 병합한다.
    {
        "canonical": ("mlbam", "808982"),
        "native_name": "이정후",
        "note": "Jung Hoo Lee KBO 키움(2020) → MLB Giants(2024, StatsAPI season)",
    },
]


# --------------------------------------------------------------------------- #
# 유틸
# --------------------------------------------------------------------------- #
def _norm_name(s: str | None) -> str:
    """이름 비교용 정규화: 전각(U+3000)·일반 공백 모두 제거."""
    if s is None:
        return ""
    return str(s).replace("　", "").replace(" ", "").strip()


# --------------------------------------------------------------------------- #
# 병합 엔진
# --------------------------------------------------------------------------- #
def merge_persons(
    conn: sqlite3.Connection,
    keep_id: int,
    drop_id: int,
    *,
    name_native: str | None = None,
    name_roman: str | None = None,
) -> dict[str, int]:
    """drop_id person 을 keep_id 로 병합. repoint 한 테이블별 건수를 반환.

    트랜잭션으로 묶고 commit. drop person 은 삭제된다.
    """
    if keep_id == drop_id:
        return {}
    cur = conn.cursor()
    counts: dict[str, int] = {}

    # 트랜잭션 시작(헬퍼 commit 과 분리 위해 명시적으로)
    cur.execute("BEGIN")
    try:
        # 1) person_external_id — (source, external_id) 가 keep 에 이미 있으면 drop 행 삭제
        ext_moved = 0
        ext_dropped = 0
        rows = cur.execute(
            "SELECT source, external_id FROM person_external_id WHERE person_id=?",
            (drop_id,),
        ).fetchall()
        for source, external_id in rows:
            exists = cur.execute(
                "SELECT 1 FROM person_external_id "
                "WHERE source=? AND external_id=? AND person_id=?",
                (source, external_id, keep_id),
            ).fetchone()
            if exists:
                cur.execute(
                    "DELETE FROM person_external_id "
                    "WHERE source=? AND external_id=? AND person_id=?",
                    (source, external_id, drop_id),
                )
                ext_dropped += 1
            else:
                cur.execute(
                    "UPDATE person_external_id SET person_id=? "
                    "WHERE source=? AND external_id=? AND person_id=?",
                    (keep_id, source, external_id, drop_id),
                )
                ext_moved += 1
        counts["person_external_id_moved"] = ext_moved
        counts["person_external_id_dropped"] = ext_dropped

        # 2) player_batting_game — UNIQUE(game_id, person_id) 충돌 시 drop 행 삭제
        for tbl in ("player_batting_game", "player_pitching_game"):
            moved = 0
            dropped = 0
            grows = cur.execute(
                f"SELECT id, game_id FROM {tbl} WHERE person_id=?", (drop_id,)
            ).fetchall()
            for row_id, game_id in grows:
                clash = cur.execute(
                    f"SELECT 1 FROM {tbl} WHERE game_id=? AND person_id=?",
                    (game_id, keep_id),
                ).fetchone()
                if clash:
                    cur.execute(f"DELETE FROM {tbl} WHERE id=?", (row_id,))
                    dropped += 1
                else:
                    cur.execute(
                        f"UPDATE {tbl} SET person_id=? WHERE id=?", (keep_id, row_id)
                    )
                    moved += 1
            counts[f"{tbl}_moved"] = moved
            counts[f"{tbl}_dropped"] = dropped

        # 3) stint — UNIQUE(person_id, team_season_id, order_in_season).
        #    keep 가 같은 (team_season, order) stint 를 이미 가지면 충돌하므로
        #    그 경우엔 drop stint 의 order 를 비충돌 값으로 밀어 repoint.
        stint_moved = 0
        srows = cur.execute(
            "SELECT id, team_season_id, order_in_season FROM stint WHERE person_id=?",
            (drop_id,),
        ).fetchall()
        for sid, ts_id, order_no in srows:
            clash = cur.execute(
                "SELECT 1 FROM stint WHERE person_id=? AND team_season_id=? "
                "AND order_in_season=?",
                (keep_id, ts_id, order_no),
            ).fetchone()
            if clash:
                nxt = cur.execute(
                    "SELECT COALESCE(MAX(order_in_season),0)+1 FROM stint "
                    "WHERE person_id=? AND team_season_id=?",
                    (keep_id, ts_id),
                ).fetchone()[0]
                cur.execute(
                    "UPDATE stint SET person_id=?, order_in_season=? WHERE id=?",
                    (keep_id, nxt, sid),
                )
            else:
                cur.execute(
                    "UPDATE stint SET person_id=? WHERE id=?", (keep_id, sid)
                )
            stint_moved += 1
        counts["stint_moved"] = stint_moved

        # 4) award_share — 단순 UPDATE
        cur.execute(
            "UPDATE award_share SET person_id=? WHERE person_id=?",
            (keep_id, drop_id),
        )
        counts["award_share_moved"] = cur.rowcount if cur.rowcount > 0 else 0

        # 5) postseason_series.mvp_person_id — 단순 UPDATE
        cur.execute(
            "UPDATE postseason_series SET mvp_person_id=? WHERE mvp_person_id=?",
            (keep_id, drop_id),
        )
        counts["postseason_mvp_moved"] = cur.rowcount if cur.rowcount > 0 else 0

        # 6) keep 의 원어/로마자 보강
        if name_native is not None:
            cur.execute(
                "UPDATE person SET name_native=? WHERE id=?", (name_native, keep_id)
            )
        if name_roman is not None:
            cur.execute(
                "UPDATE person SET name_roman=? WHERE id=?", (name_roman, keep_id)
            )

        # 7) drop person 삭제
        cur.execute("DELETE FROM person WHERE id=?", (drop_id,))
        counts["person_dropped"] = 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


# --------------------------------------------------------------------------- #
# 크로스워크 실행
# --------------------------------------------------------------------------- #
def run(conn: sqlite3.Connection) -> int:
    """CROSSWALK 순회 → 매칭되는 NPB person 을 MLB person 으로 병합.

    병합한 총 person 수를 반환(멱등 재실행 시 0).
    """
    cur = conn.cursor()
    total_merged = 0

    for entry in CROSSWALK:
        source, ext = entry["canonical"]
        target = _norm_name(entry["native_name"])
        note = entry.get("note", "")

        keep = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source=? AND external_id=?",
            (source, ext),
        ).fetchone()
        if not keep:
            print(f"[skip] keep 미존재 ({source}:{ext}) — {note}")
            continue
        keep_id = keep[0]

        # drop 후보: source IN ('npb','kbo') external_id 보유 + 이름 일치(공백 정규화) + keep 제외
        candidates: list[int] = []
        for (pid, name_native) in cur.execute(
            "SELECT DISTINCT p.id, p.name_native FROM person p "
            "JOIN person_external_id e ON e.person_id = p.id "
            "WHERE e.source IN ('npb','kbo')"
        ).fetchall():
            if pid == keep_id:
                continue
            if _norm_name(name_native) == target:
                candidates.append(pid)

        if not candidates:
            print(f"[noop] NPB/KBO 매칭 후보 없음 — keep={keep_id} ({entry['native_name']}) {note}")
            continue

        # keep 의 기존 로마자 유지(원어 보강). 원어 name_native 로 갱신.
        keep_roman = cur.execute(
            "SELECT name_roman FROM person WHERE id=?", (keep_id,)
        ).fetchone()[0]
        native = entry["native_name"]

        for drop_id in candidates:
            counts = merge_persons(
                conn, keep_id, drop_id,
                name_native=native, name_roman=keep_roman,
            )
            total_merged += 1
            print(f"[merge] drop={drop_id} → keep={keep_id} ({native}) {note}")
            print(f"        repoint: {counts}")

    print(f"\nperson_match run done: merged {total_merged} person(s)")
    return total_merged


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from backend.ingest.load.loader import connect

    p = argparse.ArgumentParser(prog="person_match")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run", help="CROSSWALK 순회 병합")
    pr.add_argument("--db")
    a = p.parse_args()

    conn = connect(str(a.db or DEFAULT_DB))
    if a.cmd == "run":
        run(conn)
    conn.close()
