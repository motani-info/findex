"""配当方針（doc18）の抽出・パーサ（純粋関数）の回帰テスト。

確証主義の核心（doc18 §3 B・スパイクで実証）を固定する:
- 政策文の配当性向%は多くが**実績値**（「59.2％となりました」）＝目標として採らない。
- 目標マーカーと共起した時のみ採る（リンナイ「連結配当性向40％を目指し」=40 が正）。
- 数値目標が無い社（花王）は payout_target=missing が正（捏造しない）。
- 累進/安定はリテラル検出のみ（言い換えからの推測昇格はしない）。
"""
from findex.fetch.edinet import (
    extract_dividend_policy,
    parse_policy_signals,
)


def _rec(eid, ctx, val):
    return {"要素ID": eid, "コンテキストID": ctx, "値": val}


# ── A: 生テキスト抽出 ────────────────────────────────────────
def test_extract_prefers_current_year_duration():
    recs = [
        _rec("jpcrp_cor:DividendPolicyTextBlock", "Prior1YearDuration", "旧方針"),
        _rec("jpcrp_cor:DividendPolicyTextBlock", "CurrentYearDuration", "当期方針"),
    ]
    assert extract_dividend_policy(recs) == "当期方針"


def test_extract_fallback_longest_when_no_current():
    recs = [
        _rec("jpcrp_cor:DividendPolicyTextBlock", "FilingDateInstant", "短い"),
        _rec("jpcrp_cor:DividendPolicyTextBlock", "X", "こちらの方が長い本文です"),
    ]
    assert extract_dividend_policy(recs) == "こちらの方が長い本文です"


def test_extract_missing_returns_none():
    assert extract_dividend_policy([_rec("foo", "x", "bar")]) is None
    assert extract_dividend_policy(
        [_rec("jpcrp_cor:DividendPolicyTextBlock", "X", "－")]) is None


# ── B: 実績値を目標と誤認しない（確証主義の核心） ──────────────
def test_realized_payout_not_taken_as_target():
    # 花王型: 実績のみ・数値目標なし → payout_target は missing
    text = "当社は安定的・継続的な増配を基本方針としております。当期の配当性向は59.2％となりました。"
    sig = parse_policy_signals(text)
    assert sig["payout_target_pct"] is None
    assert sig["signals_status"]["payout_target_pct"] == "missing"
    # 「安定的」はリテラルなので stable は ok
    assert sig["stable_flag"] == 1
    assert sig["signals_status"]["stable_flag"] == "ok"
    # 累進の文字列は無い
    assert sig["progressive_flag"] is None


def test_genuine_target_taken():
    # リンナイ型: 実績(50.1%となっております)は捨て、目標(40%を目指し)だけ採る
    text = ("配当性向は50.1％となっております。当社は2025年度の連結配当性向40％を目指してまいります。"
            "また総還元性向40％を目標とします。")
    sig = parse_policy_signals(text)
    assert sig["payout_target_pct"] == 40.0
    assert sig["signals_status"]["payout_target_pct"] == "ok"
    assert sig["total_payout_target_pct"] == 40.0
    assert sig["signals_status"]["total_payout_target_pct"] == "ok"


def test_progressive_literal_detected():
    sig = parse_policy_signals("当社は累進配当を導入し、減配せず配当を維持または増配します。")
    assert sig["progressive_flag"] == 1
    assert sig["signals_status"]["progressive_flag"] == "ok"


def test_doe_target_detected():
    sig = parse_policy_signals("株主資本配当率（DOE）3％以上を目標として安定配当を継続します。")
    assert sig["doe_target_pct"] == 3.0
    assert sig["signals_status"]["doe_target_pct"] == "ok"
    assert sig["stable_flag"] == 1


def test_zenkaku_normalized():
    # 全角数字・全角％でも採れる
    sig = parse_policy_signals("連結配当性向３０％以上を目標とする方針です。")
    assert sig["payout_target_pct"] == 30.0


def test_total_payout_not_confused_with_payout():
    # 総還元性向の数字を配当性向として拾わないこと
    text = "総還元性向50％を目標とします。配当性向については特に目標を定めておりません。"
    sig = parse_policy_signals(text)
    assert sig["total_payout_target_pct"] == 50.0
    assert sig["payout_target_pct"] is None


# ── B: スケール検証(全3734社)で判明した罠の回帰固定（doc18・確証主義） ──────────
def test_doe_value_not_bled_into_payout():
    # 3512型: 「配当性向を加味しDOE2.5%を目標」→ 2.5はDOE目標。payoutに混入させない。
    text = "配当性向を加味しＤＯＥ2.5％を目標として、安定的な配当を実施します。"
    sig = parse_policy_signals(text)
    assert sig["payout_target_pct"] is None          # DOE値をpayoutに入れない
    assert sig["doe_target_pct"] == 2.5              # 正しくDOE側へ


def test_realized_in_parens_with_houshin_not_taken():
    # 9733型: 「方針に基づき…（配当性向：100.9%）といたしました」← 実績。方針語があっても採らない。
    text = "上記方針に基づき、1株当たり100円（配当性向：100.9％）といたしました。"
    sig = parse_policy_signals(text)
    assert sig["payout_target_pct"] is None
    assert sig["signals_status"]["payout_target_pct"] == "missing"


def test_realized_decided_not_taken():
    # 3079型: 「（配当性向 127.6%）…実施することを決定」← 実績/確定。採らない。
    text = "上記方針に基づき1株当たり50.00円(配当性向 127.6%)の普通配当を実施することを決定いたしました。"
    sig = parse_policy_signals(text)
    assert sig["payout_target_pct"] is None


def test_narimasu_outcome_not_taken():
    # 9744型: 「連結配当性向は120%となります」← 結果。採らない。
    text = "年間配当88円とする予定であり、これにより連結配当性向は120％となります。"
    sig = parse_policy_signals(text)
    assert sig["payout_target_pct"] is None


def test_cap_below_not_taken_as_target():
    # 8999/9788型: 「配当性向100%以下/以内を目安」← 上限であって目標ではない。
    assert parse_policy_signals("配当性向100％以下を目安に決定します。")["payout_target_pct"] is None
    assert parse_policy_signals("配当性向100％以内の方針に基づき決定します。")["payout_target_pct"] is None


def test_genuine_floor_still_taken():
    # 「30%以上」は下限＝目標として残す（上限除外で誤って消さないこと）。
    assert parse_policy_signals("連結配当性向30％以上を目指します。")["payout_target_pct"] == 30.0


def test_empty_text_all_missing():
    sig = parse_policy_signals(None)
    for k in ("progressive_flag", "stable_flag", "payout_target_pct",
              "doe_target_pct", "total_payout_target_pct"):
        assert sig[k] is None
        assert sig["signals_status"][k] == "missing"
