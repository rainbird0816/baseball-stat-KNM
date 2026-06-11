"""Lahman DB → 코어 스키마 컬럼 매핑.

Lahman 의 컬럼명을 코어 테이블 컬럼으로 옮기는 사전(dict).
normalize 단계에서 pandas DataFrame.rename(columns=...) 으로 사용한다.

원칙
- 원본 CSV 전체를 모델 컨텍스트에 넣지 않는다. df.columns / df.head() 요약만 본다.
- 일부 컬럼은 직접 대응이 없어 파생이 필요하다(아래 DERIVED 주석 참고).
- Lahman 의 IPouts 는 이미 '아웃 수'라 ip_outs 로 직행한다.
"""

# People.csv → person
PEOPLE = {
    # lahman_col: core_col
    "nameGiven": "name_native",   # 임시: 전체 이름. roman 은 nameFirst+nameLast 로 별도 구성
    "birthDateISO": "birth_date", # DERIVED: birthYear/Month/Day 조합
    "bats": "bats",
    "throws": "throws",
    "debut": "debut_date",
}
# DERIVED(person):
#   name_roman   = f"{nameFirst} {nameLast}"
#   birth_date   = f"{birthYear:04d}-{birthMonth:02d}-{birthDay:02d}" (결측 허용)
# 외부 ID(person_external_id) 로 분리 적재:
#   ('bbref',  bbrefID), ('retrosheet', retroID), ('lahman', playerID)

# Teams.csv → team_season
TEAMS = {
    "name": "team_name",
    "W": "wins",
    "L": "losses",
    # ties: Lahman Teams 에는 보통 없음 → 0
}
# DERIVED(team_season):
#   franchise_id ← franchID 매핑(TeamsFranchises.csv)
#   season_id    ← (league='MLB', year=yearID)
#   org_id       ← lgID(+divID) → organization 매핑
#   park_id      ← park 명 → park 매핑
#   source       = 'lahman'

# Batting.csv → batting_season
BATTING = {
    "G": "g",
    "AB": "ab",
    "R": "r",
    "H": "h",
    "2B": "b2",
    "3B": "b3",
    "HR": "hr",
    "RBI": "rbi",
    "SB": "sb",
    "CS": "cs",
    "BB": "bb",
    "SO": "so",
    "IBB": "ibb",
    "HBP": "hbp",
    "SH": "sh",
    "SF": "sf",
    "GIDP": "gidp",
}
# DERIVED(batting_season):
#   pa = AB + BB + HBP + SF + SH   (Lahman 에 PA 컬럼 없음)
#   stint_id ← (playerID, yearID, teamID, stint) → stint 매핑
#   source   = 'lahman'

# Pitching.csv → pitching_season
PITCHING = {
    "W": "w",
    "L": "l",
    "G": "g",
    "GS": "gs",
    "CG": "cg",
    "SHO": "sho",
    "SV": "sv",
    "IPouts": "ip_outs",   # 이미 아웃 단위 → 직행
    "H": "h",
    "R": "r",
    "ER": "er",
    "HR": "hr",
    "BB": "bb",
    "SO": "so",
    "HBP": "hbp",
    "BK": "bk",
    "WP": "wp",
    "BFP": "bf",
}
# DERIVED(pitching_season):
#   hld(홀드): Lahman 구버전엔 없을 수 있음 → 결측 허용
#   stint_id, source 는 batting 과 동일

# Fielding.csv → fielding_season
FIELDING = {
    "POS": "pos",
    "G": "g",
    "GS": "gs",
    "InnOuts": "inn_outs",
    "PO": "po",
    "A": "a",
    "E": "e",
    "DP": "dp",
    "PB": "pb",
    "SB": "sb_c",   # 포수 상대 도루 허용
    "CS": "cs_c",   # 포수 도루 저지
}

# AwardsPlayers.csv → award_share
AWARDS = {
    "awardID": "award",
    # vote_pct 는 AwardsSharePlayers.csv 에서 별도(pointsWon/pointsMax)
}

# SeriesPost.csv → postseason_series
SERIES_POST = {
    "round": "round",          # 'WS','ALCS','NLCS','ALDS1',...
    "wins": "wins",
    "losses": "losses",
    "ties": "ties",
}
# DERIVED(postseason_series):
#   league          = 'MLB'
#   is_championship = 1 if round == 'WS' else 0
#   winner_ts_id ← (teamIDwinner, yearID) → team_season
#   loser_ts_id  ← (teamIDloser,  yearID) → team_season

# round → is_championship 판정 (리그별 우승 결정전)
CHAMPIONSHIP_ROUNDS = {
    "WS",              # MLB World Series
    "JapanSeries",     # NPB
    "KoreanSeries",    # KBO
}

# Lahman lgID → organization.short_code
LGID_TO_ORG = {
    "AL": "AL",
    "NL": "NL",
}
