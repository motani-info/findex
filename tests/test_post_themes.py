"""X投稿テーマの純関数テスト（Phase6 MVP・品質ゲートの回帰防止）。"""
from findex.post.themes import (
    _hy_safe_eligible, _non_financial, _SPECS, _streak_body, _yoc_quality_key,
    weighted_len,
)


def _row(**kw):
    """テーマフィルタ用の最小行（不要キーは None 既定）。指定キーだけ上書き。"""
    base = {
        "dy": None, "gd": None, "rel": None, "payout_ratio": None,
        "g_years": None, "yoc": None, "fcf_payout_coverage": None,
        "roe": None, "roic_minus_wacc": None, "sector33": None,
    }
    base.update(kw)
    return base


def test_weighted_len_cjk_is_2():
    assert weighted_len("abc") == 3            # ASCII=1
    assert weighted_len("増配") == 4           # CJK=2
    assert weighted_len("a増") == 3            # 混在


def test_streak_body_within_140():
    # フック本文は加重140字以内（Xバッジ無しアカウント制約）。
    # 2桁トップN（最長想定）でも超えないこと＝看板を伸ばす改変への歯止め。
    for n in (5, 10, 20, 99):
        assert weighted_len(_streak_body(n)) <= 140, n


def test_streak_body_contains_thesis_and_gate():
    body = _streak_body(10)
    assert "続く配当" in body          # 差別化テーゼ
    assert "status=ok" not in body     # FB是正: 利用者に無意味なメタ表現は本文に出さない
    assert "#増配株" in body and "#高配当株" in body   # ハッシュタグは2個・株サフィックス統一
    assert "#日本株" not in body       # 汎用すぎるタグは付けない


# ── P1: テーマ層較正（doc 10・GeminiFB是正）の回帰防止 ──────────────────

def test_hy_safe_excludes_unsafe_high_yield():
    """high_yield_safe: 高利回り×減配常習×配当性向>100%の罠（バリューコマース型）を除外。"""
    # 安全な高配当（gradeA・減配信頼性1.0・配当性向50%）は通過
    assert _hy_safe_eligible(_row(dy=0.04, gd="A", rel=1.0, payout_ratio=0.5))
    # 減配常習（rel=0.0=過去20年で2回以上減配）は看板「減配しにくい」に反する→除外
    assert not _hy_safe_eligible(_row(dy=0.06, gd="A", rel=0.0, payout_ratio=0.5))
    # 配当性向>100%（利益で配当を賄えていない＝バリューコマース217%型）は除外
    assert not _hy_safe_eligible(_row(dy=0.06, gd="A", rel=1.0, payout_ratio=2.17))
    # rel/payout 未算出（確証なし）は安全性を保証できず除外
    assert not _hy_safe_eligible(_row(dy=0.06, gd="A", rel=None, payout_ratio=0.5))
    assert not _hy_safe_eligible(_row(dy=0.06, gd="A", rel=1.0, payout_ratio=None))
    # 利回りフロア未満（高配当を名乗れない）は除外
    assert not _hy_safe_eligible(_row(dy=0.01, gd="A", rel=1.0, payout_ratio=0.5))


def test_yoc_quality_key_demotes_cyclical():
    """div_growth: YoC×質係数。一過性(cyclical)はYoCが多少高くても持続的増配に負ける。"""
    sound = _row(yoc=0.20, quality="sound")        # 0.20×1.0 = 0.20
    cyclical = _row(yoc=0.34, quality="cyclical")  # 0.34×0.3 = 0.102（高YoCでも沈む）
    assert _yoc_quality_key(sound) > _yoc_quality_key(cyclical)
    # 性向拡大依存は中間（×0.5）
    payout = _row(yoc=0.30, quality="payout_driven")  # 0.30×0.5 = 0.15
    assert _yoc_quality_key(sound) > _yoc_quality_key(payout) > _yoc_quality_key(cyclical)
    # 質未算出は採点層と同じく ×1.0（既定）
    assert _yoc_quality_key(_row(yoc=0.10, quality=None)) == 0.10


def test_growth_room_requires_fcf_coverage():
    """growth_room: 低配当性向だけでなく FCF が配当を賄えている（>0）裏付けを要求。"""
    elig = _SPECS["growth_room"]["eligible"]
    base = dict(gd="A", payout_ratio=0.3, g_years=10, dy=0.025)
    assert elig(_row(**base, fcf_payout_coverage=2.0))       # 現金で賄える＝余力あり
    assert not elig(_row(**base, fcf_payout_coverage=None))  # FCF未算出は裏付けなし→除外
    assert not elig(_row(**base, fcf_payout_coverage=-1.0))  # FCFマイナス＝賄えない→除外


def test_roic_spread_requires_roe():
    """roic_spread: ROIC−WACC>0だけでなくROE算出済み（分母崩壊系=千代田化工型を除外）。"""
    elig = _SPECS["roic_spread"]["eligible"]
    assert elig(_row(roic_minus_wacc=0.05, roe=0.12))      # 健全
    assert not elig(_row(roic_minus_wacc=0.05, roe=None))  # ROE算出不能→除外
    assert not elig(_row(roic_minus_wacc=-0.01, roe=0.12)) # 価値破壊（負）→除外


def test_non_financial_excludes_financial_sectors():
    """CF系テーマ: 銀行/証券/保険/その他金融を除外（FCF・ネットキャッシュの概念が不適）。"""
    assert not _non_financial(_row(sector33="銀行業"))
    assert not _non_financial(_row(sector33="証券、商品先物取引業"))
    assert not _non_financial(_row(sector33="保険業"))
    assert not _non_financial(_row(sector33="その他金融業"))
    assert _non_financial(_row(sector33="情報・通信業"))    # 非金融は通過
    assert _non_financial(_row(sector33=None))               # 未取得は従来挙動（除外しない）


def test_fcf_coverage_excludes_financials():
    """fcf_coverage: 金融除外がeligibleに効く（GeminiFB: 銀行独占の是正）。"""
    elig = _SPECS["fcf_coverage"]["eligible"]
    base = dict(gd="A", fcf_payout_coverage=3.0, dy=0.025)
    assert elig(_row(**base, sector33="機械"))       # 非金融は通過
    assert not elig(_row(**base, sector33="銀行業"))  # 銀行は除外


# ── P3-1: 数理不変条件 nc>=g の表示担保（doc 10・override逆転の是正）──────────

def _streak_row(**kw):
    """連続年数表示テスト用の行（g/nc/censored/g_src を上書き）。"""
    base = {"g_years": None, "nc_years": None, "censored": False,
            "g_src": None, "nc_src": None}
    base.update(kw)
    return base


def test_nc_floor_lifts_when_override_growth_exceeds_computed_no_cut():
    """連続増配(override) > 連続非減配(自前計算) のとき、非減配を g 年以上（打ち切り）へ。"""
    from findex.post.report import _nc_display_floor
    # ZAi公表override で連続増配36年、自前計算の非減配は12年（データ下限）。
    # 数理上 非減配 >= 増配=36 ゆえ「36年以上」へ引き上げ（不可能な逆転を解消）。
    yrs, cen = _nc_display_floor(_streak_row(g_years=36, nc_years=12, g_src="override"))
    assert yrs == 36 and cen is True


def test_nc_floor_keeps_computed_when_consistent():
    """逆転がない（nc>=g）場合は計算値と元の打ち切りフラグをそのまま使う。"""
    from findex.post.report import _nc_display_floor
    # 非減配20 >= 増配12 ＝整合。引き上げない。
    assert _nc_display_floor(_streak_row(g_years=12, nc_years=20, g_src="override")) == (20, False)
    # g が override でない（自前計算同士）なら逆転は起きない前提＝そのまま。
    assert _nc_display_floor(_streak_row(g_years=15, nc_years=10, g_src=None)) == (10, False)
    # 元から打ち切りなら維持。
    assert _nc_display_floor(_streak_row(g_years=8, nc_years=12, censored=True)) == (12, True)


def test_nc_floor_handles_missing_values():
    """None は安全に素通し（捏造しない）。"""
    from findex.post.report import _nc_display_floor
    assert _nc_display_floor(_streak_row(g_years=36, nc_years=None, g_src="override")) == (None, False)
    assert _nc_display_floor(_streak_row(g_years=None, nc_years=10)) == (10, False)


def test_streak_td_nc_renders_n_plus_on_inversion():
    """表示セル: 逆転時に非減配が『36年以上』とレンダリングされる（report.py合成を経由）。"""
    from findex.post.themes import _streak_td
    cell = _streak_td(_streak_row(g_years=36, nc_years=12, g_src="override"), "nc")
    assert "36年以上" in cell
    # 増配側（g）は override 確定値ゆえそのまま「36年」（以上は付かない）。
    assert "年以上" not in _streak_td(_streak_row(g_years=36, nc_years=12, g_src="override"), "g")
