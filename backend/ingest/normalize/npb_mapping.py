"""NPB 정규화 매핑 (Phase 4).

npb.jp BIS stats 표의 일본어 표기 → 코어 스키마 코드/컬럼 매핑을 모은다.
원본 HTML 은 컨텍스트에 넣지 않으며, 여기 매핑은 inspect 로 확인한 표 헤더에 근거한다.

확인 출처: data/raw/npb/2022/{bat,pit,std}_{c,p}.html (npb.jp BIS, 2022)
"""
from __future__ import annotations

# ---- franchise 정의 (코드 / 리그 org_id / 표기) ------------------------------
# org_id: 21=Central League, 22=Pacific League (organization 시드)
# abbr   : 타격/투구 표의 球団 약어( '(ヤ)' 의 안쪽 한 글자 )
# std_key: 순위표 팀 풀네임에 들어있는 식별 부분문자열
# 각 항목: code -> dict
NPB_FRANCHISES: dict[str, dict] = {
    # ----- Central League (org_id=21) -----
    "YOG": {
        "org_id": 21, "abbr": "巨", "std_key": "ジャイアンツ",
        "name_native": "読売ジャイアンツ", "name_roman": "Yomiuri Giants",
        "lineage": "読売ジャイアンツ", "founded_year": 1934,
    },
    "HT": {
        "org_id": 21, "abbr": "神", "std_key": "タイガース",
        "name_native": "阪神タイガース", "name_roman": "Hanshin Tigers",
        "lineage": "大阪タイガース→阪神タイガース", "founded_year": 1935,
    },
    "HC": {
        "org_id": 21, "abbr": "広", "std_key": "カープ",
        "name_native": "広島東洋カープ", "name_roman": "Hiroshima Toyo Carp",
        "lineage": "広島カープ→広島東洋カープ", "founded_year": 1950,
    },
    "YDB": {
        "org_id": 21, "abbr": "デ", "std_key": "ベイスターズ",
        "name_native": "横浜DeNAベイスターズ", "name_roman": "Yokohama DeNA BayStars",
        "lineage": "大洋ホエールズ→横浜ベイスターズ→横浜DeNAベイスターズ",
        "founded_year": 1950,
    },
    "YS": {
        "org_id": 21, "abbr": "ヤ", "std_key": "スワローズ",
        "name_native": "東京ヤクルトスワローズ", "name_roman": "Tokyo Yakult Swallows",
        "lineage": "国鉄スワローズ→ヤクルトスワローズ→東京ヤクルトスワローズ",
        "founded_year": 1950,
    },
    "CD": {
        "org_id": 21, "abbr": "中", "std_key": "ドラゴンズ",
        "name_native": "中日ドラゴンズ", "name_roman": "Chunichi Dragons",
        "lineage": "名古屋軍→中日ドラゴンズ", "founded_year": 1936,
    },
    # ----- Pacific League (org_id=22) -----
    "SBH": {
        "org_id": 22, "abbr": "ソ", "std_key": "ホークス",
        "name_native": "福岡ソフトバンクホークス",
        "name_roman": "Fukuoka SoftBank Hawks",
        "lineage": "南海ホークス→福岡ダイエーホークス→福岡ソフトバンクホークス",
        "founded_year": 1938,
    },
    "ORX": {
        "org_id": 22, "abbr": "オ", "std_key": "バファローズ",
        "name_native": "オリックス・バファローズ",
        "name_roman": "Orix Buffaloes",
        "lineage": "阪急ブレーブス→オリックス・ブルーウェーブ→オリックス・バファローズ",
        "founded_year": 1936,
    },
    "CLM": {
        "org_id": 22, "abbr": "ロ", "std_key": "マリーンズ",
        "name_native": "千葉ロッテマリーンズ",
        "name_roman": "Chiba Lotte Marines",
        "lineage": "毎日オリオンズ→ロッテオリオンズ→千葉ロッテマリーンズ",
        "founded_year": 1950,
    },
    "SSL": {
        "org_id": 22, "abbr": "西", "std_key": "ライオンズ",
        "name_native": "埼玉西武ライオンズ",
        "name_roman": "Saitama Seibu Lions",
        "lineage": "西鉄ライオンズ→西武ライオンズ→埼玉西武ライオンズ",
        "founded_year": 1950,
    },
    "RGE": {
        "org_id": 22, "abbr": "楽", "std_key": "ゴールデンイーグルス",
        "name_native": "東北楽天ゴールデンイーグルス",
        "name_roman": "Tohoku Rakuten Golden Eagles",
        "lineage": "東北楽天ゴールデンイーグルス", "founded_year": 2005,
    },
    "NHF": {
        "org_id": 22, "abbr": "日", "std_key": "ファイターズ",
        "name_native": "北海道日本ハムファイターズ",
        "name_roman": "Hokkaido Nippon-Ham Fighters",
        "lineage": "東映フライヤーズ→日本ハムファイターズ→北海道日本ハムファイターズ",
        "founded_year": 1946,
    },
}

# 球団 약어(한 글자) -> franchise code (타격/투구 표용)
ABBR_TO_CODE: dict[str, str] = {v["abbr"]: k for k, v in NPB_FRANCHISES.items()}


def code_for_abbr(abbr: str) -> str | None:
    """ '(ヤ)' 또는 'ヤ' -> 'YS'. 모르면 None."""
    if abbr is None:
        return None
    a = abbr.strip().strip("()（）").strip()
    return ABBR_TO_CODE.get(a)


def code_for_standings_name(full_name: str) -> str | None:
    """순위표 팀 풀네임(예 '東京ヤクルト スワローズ') -> franchise code.

    풀네임에 std_key 부분문자열이 들어있는지로 매칭(공백/표기 변형에 강건).
    """
    if full_name is None:
        return None
    name = str(full_name).replace("　", "").replace(" ", "")
    for code, v in NPB_FRANCHISES.items():
        if v["std_key"].replace(" ", "") in name:
            return code
    return None


# ---- subleague 페이지 코드 -> org_id ---------------------------------------
PAGE_ORG = {"c": 21, "p": 22}  # central / pacific


# ---- 타격 표 컬럼 인덱스 (row1 헤더 기준, 0-base) ---------------------------
# [0]順位 [1-2]選手(이름) [2]球団약어 [3]打率 [4]試合G [5]打席PA [6]打数AB
# [7]得点R [8]安打H [9]二塁打2B [10]三塁打3B [11]本塁打HR [12]塁打TB
# [13]打点RBI [14]盗塁SB [15]盗塁刺CS [16]犠打SH [17]犠飛SF [18]四球BB
# [19]故意四IBB [20]死球HBP [21]三振SO [22]併殺打GIDP [23]長打率 [24]出塁率
BAT_COL = {
    "name": 1, "team": 2, "g": 4, "pa": 5, "ab": 6, "r": 7, "h": 8,
    "b2": 9, "b3": 10, "hr": 11, "rbi": 13, "sb": 14, "cs": 15,
    "sh": 16, "sf": 17, "bb": 18, "ibb": 19, "hbp": 20, "so": 21, "gidp": 22,
}

# ---- 투구 표 컬럼 인덱스 (row1 헤더 기준, 0-base) ---------------------------
# [0]順位 [1-2]投手(이름) [2]球団 [3]防御率 [4]登板G [5]勝利W [6]敗北L
# [7]セーブSV [8]ホールドHLD [9]HP [10]完投CG [11]完封勝SHO [12]無四球
# [13]勝率 [14]打者BF [15]投球回(정수) [16]投球回(소수.1/.2) [17]安打H
# [18]本塁打HR [19]四球BB [20]故意四 [21]死球HBP [22]三振SO [23]暴投WP
# [24]ボークBK [25]失点R [26]自責点ER
PIT_COL = {
    "name": 1, "team": 2, "g": 4, "w": 5, "l": 6, "sv": 7, "hld": 8,
    "cg": 10, "sho": 11, "bf": 14, "ip_whole": 15, "ip_frac": 16,
    "h": 17, "hr": 18, "bb": 19, "ibb": 20, "hbp": 21, "so": 22,
    "wp": 23, "bk": 24, "r": 25, "er": 26,
}

# ---- 순위표 컬럼 인덱스 (row0 헤더 기준, 0-base) ---------------------------
# [0]チーム [1]試合 [2]勝利W [3]敗北L [4]引分T [5]勝率 ...
STD_COL = {"name": 0, "g": 1, "w": 2, "l": 3, "t": 4}


def ip_to_outs(whole, frac) -> int | None:
    """NPB 투구 이닝 → 아웃 정수.

    whole = 정수 이닝(예 '162', '166'), frac = '.1'(1/3) / '.2'(2/3) / ''/'.0'(0).
    outs = whole*3 + {.1:1, .2:2}. 예) 166 + '.2' → 166*3+2 = 500.
    """
    import math

    if whole is None:
        return None
    try:
        if isinstance(whole, float) and math.isnan(whole):
            return None
    except TypeError:
        pass
    ws = str(whole).strip()
    if ws in ("", "nan", "-"):
        return None
    try:
        w = int(float(ws))
    except (ValueError, TypeError):
        return None
    add = 0
    if frac is not None:
        fs = str(frac).strip()
        if fs not in ("", "nan", "-", ".0", "0"):
            # '.1' -> 1, '.2' -> 2  (소수 첫째 자리 = 1/3 단위)
            digit = fs.lstrip(".").strip()
            if digit.isdigit():
                add = int(digit[0])
    return w * 3 + add
