"""X投稿テーマの純関数テスト（Phase6 MVP・品質ゲートの回帰防止）。"""
from findex.post.themes import (
    BODY_MAX, _body_metric, _hy_safe_eligible, _is_takoashi, _net_cash_eligible,
    _non_financial, _post_name, _post_name_block, _SPECS, _streak_body, _yoc_quality_key,
    weighted_len,
)


def _row(**kw):
    """テーマフィルタ用の最小行（不要キーは None 既定）。指定キーだけ上書き。"""
    base = {
        "dy": None, "gd": None, "rel": None, "payout_ratio": None,
        "g_years": None, "yoc": None, "fcf_payout_coverage": None,
        "roe": None, "roic_minus_wacc": None, "sector33": None,
        "pbr": None, "current_market_cap": None, "operating_margin": None,
        "gh": None, "quality": None, "total": None, "net_cash_per": None,
        "per": None, "equity_ratio": None,
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


# ── doc16: 投稿本文へトップ3社＋看板指標を注入（引きを強める）─────────────────

def test_post_name_normalizes_fullwidth_and_clips():
    # 全角英数は半角化（読みやすさ・字数節約）、カナはそのまま、長名は末尾省略。
    assert _post_name("ＺＯＺＯ") == "ZOZO"
    assert _post_name("三菱ＨＣキャピタル") == "三菱HCキャピタル"
    assert _post_name("サイボウズ") == "サイボウズ"
    clipped = _post_name("ジェイエイシーリクルートメント")
    assert clipped.endswith("…") and len(clipped) == 12


def test_body_metric_formats_by_kind():
    assert _body_metric(0.036044, "pct") == "3.6%"
    assert _body_metric(0.343099, "pct_signed") == "＋34.3%"
    assert _body_metric(-0.05, "pct_signed") == "−5.0%"
    assert _body_metric(36, "year") == "36年"
    assert _body_metric(2.0123, "x") == "2.0倍"
    assert _body_metric(70.7, "num") == "70.7"
    assert _body_metric(None, "pct") == "—"      # 未算出は素直にダッシュ


def test_post_name_block_builds_medal_lines():
    shown = [{"name": "ＺＯＺＯ", "roic_minus_wacc": 0.343},
             {"name": "サイボウズ", "roic_minus_wacc": 0.343},
             {"name": "JAC", "roic_minus_wacc": 0.327},
             {"name": "四位", "roic_minus_wacc": 0.30}]
    block = _post_name_block(shown, ("roic_minus_wacc", "pct_signed"))
    assert block == "🥇ZOZO ＋34.3%\n🥈サイボウズ ＋34.3%\n🥉JAC ＋32.7%\n"  # トップ3のみ・末尾改行
    assert _post_name_block([], ("roic_minus_wacc", "pct_signed")) == ""    # 該当0社は空
    assert _post_name_block(shown, None) == ""                              # headline無しは空


def test_spec_body_fn_injects_names_within_limit():
    # 全宣言テーマの body_fn が (n, names) を受け、names を本文へ差し込み BODY_MAX 以内。
    names = "🥇ZOZO ＋34.3%\n🥈サイボウズ ＋34.3%\n🥉JAC ＋32.7%\n"
    for name, spec in _SPECS.items():
        body = spec["body_fn"](5, names)
        assert "🥇ZOZO" in body, name
        assert weighted_len(body) <= BODY_MAX, (name, weighted_len(body))
        assert "headline" in spec and spec["headline"], name


def test_streak_body_injects_names():
    body = _streak_body(5, "🥇花王 36年\n🥈SPK 28年\n🥉三菱HCキャピタル 27年\n")
    assert "🥇花王 36年" in body
    assert weighted_len(body) <= BODY_MAX


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


# ── doc 12: タコ足ゾンビ除外＋生利回り系の罠是正（GeminiFB是正）──────────────

def test_is_takoashi_predicate():
    """タコ足ゾンビ＝利益超の配当(payout>100%)×減配常習(rel<0.6/未確証)。実績株は除外しない。"""
    # 減配常習×タコ足（バリューコマース217%/rel0.0・ヘリオステクノ227%/rel0.0）＝罠
    assert _is_takoashi(_row(payout_ratio=2.17, rel=0.0))
    assert _is_takoashi(_row(payout_ratio=1.5, rel=0.0))
    # rel 未確証（None）も安全性を保証できず罠扱い（厳格側）
    assert _is_takoashi(_row(payout_ratio=1.5, rel=None))
    # payout>100% でも rel が高い実績株（アイティメディアgradeA/rel1.0型）は一時的減益＝除外しない
    assert not _is_takoashi(_row(payout_ratio=1.3, rel=1.0))
    assert not _is_takoashi(_row(payout_ratio=1.3, rel=0.6))
    # payout が健全域（<=100%）はそもそもタコ足でない
    assert not _is_takoashi(_row(payout_ratio=0.5, rel=0.0))
    # payout 未算出（None）は判定材料なし＝罠としない（捏造しない）
    assert not _is_takoashi(_row(payout_ratio=None, rel=0.0))


def test_raw_yield_themes_exclude_takoashi():
    """high_yield/low_pbr_yield/small_value: タコ足ゾンビを除外。健全な高payout実績株は残す。"""
    tako = dict(payout_ratio=2.17, rel=0.0)        # 減配常習タコ足（除外対象）
    safe = dict(payout_ratio=1.3, rel=1.0)         # 高payoutだが実績あり（残す）
    cases = {
        "high_yield": dict(dy=0.10, gd="C"),
        "low_pbr_yield": dict(dy=0.10, gd="C", pbr=0.8),
        "small_value": dict(dy=0.10, gd="C", pbr=0.8, current_market_cap=2e10),
    }
    for name, base in cases.items():
        elig = _SPECS[name]["eligible"]
        assert not elig(_row(**base, **tako)), name   # タコ足は除外
        assert elig(_row(**base, **safe)), name        # 実績ある高payout株は通過


# ── doc 14: net_cash 無配排除フロア＋large_cap 総合スコア降順（GeminiFB是正）──────

def test_net_cash_excludes_munhai_keeps_low_yield_value():
    """net_cash: 無配のキャッシュトラップを排除。低配当でも現金潤沢な割安株は温存（doc14・1.5%フロア）。"""
    base = dict(net_cash_per=2.0, per=10.0, sector33="情報・通信業")  # 実質PER<表面PER＝真に現金潤沢
    # 無配(0%)＝キャッシュトラップは除外（イトクロ/キッズスター型）
    assert not _net_cash_eligible(_row(**base, dy=0.0))
    # 利回り未算出（stale/missing）も除外（確証なし）
    assert not _net_cash_eligible(_row(**base, dy=None))
    # 1.5%未満の超低配当は除外
    assert not _net_cash_eligible(_row(**base, dy=0.01))
    # 1.5%以上＝低配当でも現金潤沢な真の割安株は温存（バリュー主旨）
    assert _net_cash_eligible(_row(**base, dy=0.02))
    # 純負債（実質PER>=表面PER）は「潤沢」と誤ラベルしない
    assert not _net_cash_eligible(_row(dy=0.04, net_cash_per=11.0, per=10.0, sector33="機械"))
    # 金融は概念不適で除外（フロアを満たしても）
    assert not _net_cash_eligible(_row(dy=0.04, net_cash_per=2.0, per=10.0, sector33="銀行業"))


def test_cell_plain_kinds_do_not_highlight():
    """配当性向・PERは「高い＝良い」でないため非強調(pct_plain/x_plain)。10超でもtealにしない。"""
    from findex.post.themes import _cell
    # 通常の pct/x は10超で強調（既存挙動）
    assert "hot" in _cell(_row(payout_ratio=0.36), "payout_ratio", "pct")
    assert "hot" in _cell(_row(per=13.0), "per", "x")
    # 非強調版は10超でも光らない（性向36%/PER13倍）
    assert "hot" not in _cell(_row(payout_ratio=0.36), "payout_ratio", "pct_plain")
    assert "35.9%" in _cell(_row(payout_ratio=0.359), "payout_ratio", "pct_plain")
    assert "hot" not in _cell(_row(per=13.0), "per", "x_plain")
    assert "13.0倍" in _cell(_row(per=13.0), "per", "x_plain")


def test_std_cols_builds_8axis_with_total_right():
    """標準列: テーマ固有＋コア補充＋総合スコア(右端固定)で8軸。重複keyは固有優先・配当性向は非強調。"""
    from findex.post.themes import _std_cols, _STD_DATA_COLS
    cols = _std_cols([("PER", "per", "x_plain")])   # large_cap の signature
    assert cols[-1] == ("総合スコア", "total", "num")          # 総合スコアは右端固定
    assert len(cols) == _STD_DATA_COLS + 1                     # データ6列＋総合
    # 配当利回り(行頭)＋データ6＋総合 = 8軸
    head = 1 + len(cols)
    assert head == 8
    kinds = {c[1]: c[2] for c in cols}
    assert kinds["payout_ratio"] == "pct_plain"   # 配当性向は非強調（高い=良いでない）
    assert kinds["roe"] == "pct"                   # ROEは強調維持（高い=良い）
    # 固有keyがコアと重複する場合は固有を優先し二重化しない
    cols2 = _std_cols([("連続増配", "g_years", "streak_g")])
    assert [c[1] for c in cols2].count("g_years") == 1


def test_large_cap_uses_signature_and_sorts_by_total():
    """large_cap: signature=PER、total降順、抽出条件は不変。"""
    spec = _SPECS["large_cap"]
    assert ("PER", "per", "x_plain") in spec["signature"]


def test_large_cap_sorts_by_total_not_market_cap():
    """large_cap: 並びは総合スコア降順（旧=時価総額降順の見せ方の嘘を是正）。抽出条件は不変。"""
    spec = _SPECS["large_cap"]
    big_low = _row(total=70.0, current_market_cap=14e12, gd="B", dy=0.03)   # 巨大だがスコア低
    small_high = _row(total=90.0, current_market_cap=1.1e12, gd="A", dy=0.035)  # 小さめだがスコア高
    # スコアが高い方が上位（時価総額が小さくても勝つ）
    assert spec["sort_key"](small_high) > spec["sort_key"](big_low)
    # 抽出条件は据え置き: gradeA/B × 時価総額1兆超 × 利回り3%以上
    assert spec["eligible"](_row(gd="A", current_market_cap=1.5e12, dy=0.03))
    assert not spec["eligible"](_row(gd="C", current_market_cap=1.5e12, dy=0.03))   # grade不足
    assert not spec["eligible"](_row(gd="A", current_market_cap=9e11, dy=0.03))     # 1兆未満
    assert not spec["eligible"](_row(gd="A", current_market_cap=1.5e12, dy=0.02))   # 利回り3%未満


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
