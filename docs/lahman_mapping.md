# Lahman → 코어 스키마 매핑 레퍼런스

Phase 1(MLB 시즌 스탯)에서 사용. 코드 매핑은 `backend/ingest/normalize/lahman_mapping.py`.
이 문서는 사람이 읽는 요약. **원본 CSV 전체를 모델 컨텍스트에 넣지 말 것** — `df.columns` / `df.head()` 만 확인.

## 적재 순서 (FK 의존성)
1. `season` (year=yearID) → 2. `park` → 3. `franchise`(TeamsFranchises) → 4. `team_season`(Teams)
5. `person`(People) → 6. `stint`(Batting/Pitching/Fielding 의 키 조합) → 7. 시즌 스탯 3종 → 8. 수상/포스트시즌

## People.csv → person
| Lahman | core | 비고 |
|---|---|---|
| nameFirst + nameLast | name_roman | 문자열 결합 |
| nameGiven | name_native | 임시 |
| birthYear/Month/Day | birth_date | `YYYY-MM-DD` 조합, 결측 허용 |
| bats / throws | bats / throws | |
| debut | debut_date | |
| playerID / bbrefID / retroID | → person_external_id | source = 'lahman'/'bbref'/'retrosheet' |

## Teams.csv → team_season
| Lahman | core | 비고 |
|---|---|---|
| name | team_name | 그 시즌 명칭 |
| W / L | wins / losses | |
| franchID | → franchise_id | TeamsFranchises.csv 로 매핑 |
| yearID | → season_id | (league='MLB', year) |
| lgID (+divID) | → org_id | organization 매핑 |
| park | → park_id | park 매핑 |
| — | ties | Lahman 미제공 → 0 |

## Batting.csv → batting_season
직행: G, AB, R, H, 2B→b2, 3B→b3, HR, RBI, SB, CS, BB, SO, IBB, HBP, SH, SF, GIDP
- **파생 `pa` = AB + BB + HBP + SF + SH** (Lahman 에 PA 없음)
- 키: (playerID, yearID, teamID, stint) → `stint_id`
- `source = 'lahman'`

## Pitching.csv → pitching_season
직행: W, L, G, GS, CG, SHO, SV, **IPouts→ip_outs(아웃 단위 그대로)**, H, R, ER, HR, BB, SO, HBP, BK, WP, BFP→bf
- `hld`(홀드)는 구버전 결측 가능 → NULL 허용

## Fielding.csv → fielding_season
POS→pos, G, GS, InnOuts→inn_outs, PO→po, A→a, E→e, DP→dp, PB→pb, SB→sb_c, CS→cs_c
- 한 stint 가 여러 포지션이면 행 여러 개 (UNIQUE(stint_id, pos))

## SeriesPost.csv → postseason_series
| Lahman | core | 비고 |
|---|---|---|
| round | round | 'WS','ALCS','NLDS1'... |
| wins/losses/ties | 동일 | |
| teamIDwinner+yearID | → winner_ts_id | team_season 매핑 |
| teamIDloser+yearID | → loser_ts_id | |
| (round=='WS') | is_championship=1 | 월드시리즈 표시 |
| — | league='MLB' | |

## 검증 포인트
- 2023시즌 HR 총합 ↔ 공개 리그 총계 대조
- 트레이드 선수 stint 2개 합산 = 단일 시즌 총계
- `ip_outs // 3`, `% 3` 이 표준 이닝 표기와 일치
- SeriesPost 의 WS 승자 = 해당 연도 월드시리즈 챔피언과 일치
