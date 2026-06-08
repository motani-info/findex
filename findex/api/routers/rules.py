from fastapi import APIRouter
from pathlib import Path
import yaml

router = APIRouter(prefix="/api/rules", tags=["rules"])

RULES_PATH = Path(__file__).parent.parent.parent.parent / "rules.yaml"

# 日本語説明・定義（rules.yamlのfieldに対応）
INDICATOR_META: dict[str, dict] = {
    "consecutive_no_cut_years": {
        "label": "連続非減配年数",
        "category": "配当",
        "use_cases": ["配当株"],
        "unit": "年",
        "description": "何年間連続して配当を維持・増加させているか。リーマン・コロナ両方を耐えた証拠が最高評価。配当安定性の核心指標（最高重み）。",
        "formula": "過去の配当履歴から算出",
        "good": "17年以上（リーマン耐性）",
        "warning": "5年未満は注意",
    },
    "consecutive_dividend_growth_years": {
        "label": "連続増配年数",
        "category": "配当",
        "use_cases": ["配当株"],
        "unit": "年",
        "description": "何年間連続して配当を増やし続けているか。増配の継続は経営陣の株主還元コミットメントを示す。",
        "formula": "過去の配当履歴から算出",
        "good": "5年以上",
        "warning": "増配していなくても非減配なら一定評価",
    },
    "dividend_reliability": {
        "label": "配当信頼性スコア",
        "category": "配当",
        "use_cases": ["配当株"],
        "unit": "スコア(0〜1)",
        "description": "過去20年の配当履歴から算出。減配・無配でペナルティ。連続非減配年数の歴史的補完指標（有効率37%のため補完的位置づけ）。",
        "formula": "独自算出（減配回数・無配年数を加味）",
        "good": "0.8以上",
        "warning": "0.5未満は過去に重大な減配歴あり",
    },
    "dividend_growth_10y_cagr": {
        "label": "配当10年成長率（CAGR）",
        "category": "配当",
        "use_cases": ["配当株"],
        "unit": "%/年",
        "description": "過去10年間の配当の年複利成長率。長期的な配当成長の持続性を評価。5年CAGRより信頼性が高い（統合済み）。",
        "formula": "(直近配当 / 10年前配当)^(1/10) - 1",
        "good": "8%以上（10年で2倍超）",
        "warning": "11期未満のデータは0点",
    },
    "payout_ratio": {
        "label": "配当性向",
        "category": "配当",
        "use_cases": ["配当株"],
        "unit": "%",
        "description": "EPS（1株利益）に対する配当額の割合。低いほど増配余地がある。100%超は利益以上を配当しており危険。有効率91%の高信頼指標。",
        "formula": "年間配当額 ÷ EPS × 100",
        "good": "20〜35%",
        "warning": "100%超はpenalty_capで0点",
    },
    "fcf_payout_coverage": {
        "label": "FCF配当カバレッジ",
        "category": "配当",
        "use_cases": ["配当株"],
        "unit": "倍",
        "description": "フリーキャッシュフローが配当総額の何倍あるか。配当性向の現金ベース補完（有効率41%のため補完的位置づけ）。",
        "formula": "フリーキャッシュフロー ÷ 配当総額",
        "good": "2.0倍以上",
        "warning": "1.0未満は借入や資産売却で配当している可能性",
    },
    "eps_growth_5y": {
        "label": "EPS5年成長率",
        "category": "成長性",
        "use_cases": ["配当株"],
        "unit": "%/年",
        "description": "1株当たり利益（EPS）の過去5年間の成長率。増配の原資となる業績の成長力を示す。",
        "formula": "(直近EPS / 5年前EPS)^(1/5) - 1",
        "good": "15%以上",
        "warning": "マイナスは業績悪化",
    },
    "revenue_growth_5y_cagr": {
        "label": "売上高5年成長率（CAGR）",
        "category": "成長性",
        "use_cases": ["配当株"],
        "unit": "%/年",
        "description": "売上高の過去5年間の年複利成長率。EPSは自社株買いで水増し可能だが売上はごまかせない。EPS成長の裏付け指標。",
        "formula": "(直近売上 / 5年前売上)^(1/5) - 1",
        "good": "7%以上",
        "warning": "マイナスは縮小事業",
    },
    "equity_ratio": {
        "label": "自己資本比率",
        "category": "財務健全性",
        "use_cases": ["配当株"],
        "unit": "%",
        "description": "総資産に占める自己資本の割合。高いほど財務が安定。有効率98.8%の最信頼指標。金融業では動的に除外される。",
        "formula": "自己資本 ÷ 総資産 × 100",
        "good": "80%以上（一般事業）",
        "warning": "金融業は業種特性上スコアから除外（動的入れ替え）",
    },
    "roe": {
        "label": "ROE（自己資本利益率）",
        "category": "収益性",
        "use_cases": ["配当株"],
        "unit": "%",
        "description": "自己資本に対してどれだけ利益を生んでいるか。増配パワーの源泉となる資本効率の指標。有効率82.9%。",
        "formula": "当期純利益 ÷ 自己資本 × 100",
        "good": "20%以上",
        "warning": "5%未満は資本効率が低い",
    },
    "operating_margin": {
        "label": "営業利益率",
        "category": "収益性",
        "use_cases": ["配当株"],
        "unit": "%",
        "description": "売上高に対する営業利益の割合。本業の稼ぐ力・価格決定力・競争優位の代理指標。有効率83.6%。",
        "formula": "営業利益 ÷ 売上高 × 100",
        "good": "20%以上",
        "warning": "5%未満は競争激化・コスト高の可能性",
    },
    "roic_minus_wacc": {
        "label": "ROIC−WACC",
        "category": "収益性",
        "use_cases": ["配当株"],
        "unit": "%ポイント",
        "description": "投下資本利益率（ROIC）から加重平均資本コスト（WACC）を引いた値。プラスなら価値創造。有効率48%のため補完的位置づけ。",
        "formula": "ROIC - WACC",
        "good": "プラス（特に3%超）",
        "warning": "マイナスは価値破壊。データ欠損が多い",
    },
    "div_yield": {
        "label": "配当利回り",
        "category": "バリュエーション",
        "use_cases": ["配当株"],
        "unit": "%",
        "description": "年間配当額 ÷ 株価。3〜7%が最適ゾーン。7%超は株価下落による見かけ高利回り（利回りの罠）の可能性。",
        "formula": "年間配当額 ÷ 株価 × 100",
        "good": "3〜7%",
        "warning": "7%超はupper_capでペナルティ（逆U字型スコア）",
    },
    "net_cash_per": {
        "label": "ネットキャッシュ調整PER",
        "category": "バリュエーション",
        "use_cases": ["配当株"],
        "unit": "倍",
        "description": "時価総額からネットキャッシュを差し引いた実質事業価値に対するPER。現金を多く持つ企業を適切に評価する主指標。大型株・金融株ではmix_coefficientに入れ替わる。",
        "formula": "PER × (1 - ネットキャッシュ / 時価総額)",
        "good": "10倍以下",
        "warning": "60倍超はpenalty_capで0点",
    },
    "retained_earnings_div_ratio": {
        "label": "内部留保配当比率",
        "category": "バリュエーション",
        "use_cases": ["配当株"],
        "unit": "年",
        "description": "利益剰余金が年間配当額の何年分あるか。大型株・金融株向けのROIC-WACC代替指標（動的入れ替え）。",
        "formula": "利益剰余金 ÷ 年間配当総額",
        "good": "10年以上",
        "warning": "大型株・金融株のみ適用（動的入れ替え）",
    },
    "mix_coefficient": {
        "label": "PER×PBR（バリュエーション複合）",
        "category": "バリュエーション",
        "use_cases": ["配当株"],
        "unit": "倍²",
        "description": "PERとPBRの積。大型株・金融株向けのnet_cash_per代替指標（動的入れ替え）。低いほど割安。90超は0点。",
        "formula": "PER × PBR",
        "good": "22.5以下（PER15×PBR1.5）",
        "warning": "大型株・金融株のみ適用。90超はpenalty_capで0点",
    },
}


@router.get("/indicators")
def get_indicators():
    """全指標の定義・説明を返す"""
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            rules_data = yaml.safe_load(f)
    except Exception:
        rules_data = {}

    rules_list = rules_data.get("rules", [])
    result = []
    for rule in rules_list:
        field = rule.get("field", "")
        meta = INDICATOR_META.get(field, {})
        result.append({
            "field":       field,
            "label":       meta.get("label", field),
            "category":    meta.get("category", "その他"),
            "use_cases":   meta.get("use_cases", ["共通"]),
            "unit":        meta.get("unit", ""),
            "description": meta.get("description", ""),
            "formula":     meta.get("formula", ""),
            "good":        meta.get("good", ""),
            "warning":     meta.get("warning", ""),
            "weight":      rule.get("weight", 1.0),
            "direction":   rule.get("direction", "high"),
            "threshold":   rule.get("threshold"),
            "upper_cap":   rule.get("upper_cap"),
            "penalty_cap": rule.get("penalty_cap"),
            "applies_to":  rule.get("applies_to", []),
        })
    return {"indicators": result}


@router.get("/scoring")
def get_scoring_overview():
    """配当スコア・モメンタムスコアの指標一覧を返す"""
    # ── 配当スコア指標 ──
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            rules_data = yaml.safe_load(f)
    except Exception:
        rules_data = {}

    dividend_indicators = []
    for rule in rules_data.get("rules", []):
        field = rule.get("field", "")
        meta = INDICATOR_META.get(field, {})
        applies_to = rule.get("applies_to", [])
        dividend_indicators.append({
            "label":       meta.get("label", field),
            "description": meta.get("description", ""),
            "formula":     meta.get("formula", ""),
            "good":        meta.get("good", ""),
            "warning":     meta.get("warning", ""),
            "unit":        meta.get("unit", ""),
            "weight":      rule.get("weight", 1.0),
            "direction":   rule.get("direction", "high"),
            "threshold":   rule.get("threshold"),
            "upper_cap":   rule.get("upper_cap"),
            "penalty_cap": rule.get("penalty_cap"),
            "applies_to":  applies_to,
            "status":      "active",
        })

    # ── モメンタムスコア指標 ──
    momentum_indicators = [
        {
            "label": "3M相対リターン", "status": "active", "weight": 2.5,
            "unit": "%",
            "description": "直近3ヶ月の株価リターンからTOPIX（東証株価指数）の同期間リターンを差し引いた超過収益率。市場全体の上昇・下落の影響を除いて、その銘柄固有の強さを測る。",
            "formula": "（現在株価 ÷ 3ヶ月前株価 − 1） − （TOPIX現在値 ÷ TOPIX3ヶ月前 − 1）",
            "good": "TOPIX比+5%以上", "warning": "+30%超は過熱として0点（upper_cap）",
            "direction": "high", "threshold": 0.05, "upper_cap": 0.30, "penalty_cap": None,
            "note": "過熱（+30%超）は0点",
        },
        {
            "label": "52週高値比率", "status": "active", "weight": 2.0,
            "unit": "倍",
            "description": "現在株価が過去52週（1年間）の最高値に対してどの程度の水準にあるかを示す。0.85以上は高値圏を維持しており、上昇トレンドの継続（ブレイクアウト）シグナルとなる。",
            "formula": "現在株価 ÷ 過去52週最高値",
            "good": "0.85以上（高値の85%以上）", "warning": "0.5未満は大幅下落中",
            "direction": "high", "threshold": 0.85, "upper_cap": None, "penalty_cap": None,
            "note": None,
        },
        {
            "label": "売上成長率", "status": "active", "weight": 2.0,
            "unit": "%/年",
            "description": "過去5年間の売上高の年複利成長率（CAGR）。EPSは自社株買い等で水増し可能だが売上高はごまかせない。業績モメンタムの信頼性が高い根幹指標。",
            "formula": "（直近売上 ÷ 5年前売上）^(1/5) − 1",
            "good": "15%以上", "warning": "マイナスは縮小事業",
            "direction": "high", "threshold": 0.15, "upper_cap": None, "penalty_cap": None,
            "note": None,
        },
        {
            "label": "EPS成長率", "status": "active", "weight": 2.0,
            "unit": "%/年",
            "description": "1株当たり利益（EPS）の過去5年間の年複利成長率。配当スコアと同じデータを共有。EPSが継続的に成長している企業は機関投資家の評価が上がりやすい。",
            "formula": "（直近EPS ÷ 5年前EPS）^(1/5) − 1",
            "good": "15%以上", "warning": "マイナスは業績悪化",
            "direction": "high", "threshold": 0.15, "upper_cap": None, "penalty_cap": None,
            "note": "配当スコアと共有",
        },
        {
            "label": "12M相対リターン", "status": "active", "weight": 1.5,
            "unit": "%",
            "description": "直近12ヶ月の株価リターンからTOPIXリターンを差し引いた超過収益率。中期的に市場に勝ち続けているかを確認する。ただし12ヶ月は平均回帰の影響が出やすいため3Mより低ウェイト。",
            "formula": "（現在株価 ÷ 12ヶ月前株価 − 1） − （TOPIX現在値 ÷ TOPIX12ヶ月前 − 1）",
            "good": "TOPIX比+10%以上", "warning": "+50%超は過熱として0点（upper_cap）",
            "direction": "high", "threshold": 0.10, "upper_cap": 0.50, "penalty_cap": None,
            "note": "過熱（+50%超）は0点",
        },
        {
            "label": "ROE", "status": "active", "weight": 1.0,
            "unit": "%",
            "description": "自己資本利益率（Return on Equity）。配当スコアから流用。ROEが高い企業は機関投資家・アクティビストの注目を集めやすく、株価上昇トレンドが持続しやすい傾向がある。",
            "formula": "当期純利益 ÷ 自己資本 × 100",
            "good": "15%以上", "warning": "5%未満は資本効率が低い",
            "direction": "high", "threshold": 0.15, "upper_cap": None, "penalty_cap": None,
            "note": "配当スコアと共有",
        },
        {
            "label": "営業利益率", "status": "active", "weight": 1.0,
            "unit": "%",
            "description": "売上高に対する営業利益の割合。配当スコアから流用。収益性が高く価格決定力のある企業は、業績予想の上振れが続きやすくモメンタムが持続しやすい。",
            "formula": "営業利益 ÷ 売上高 × 100",
            "good": "15%以上", "warning": "5%未満は競争激化・コスト高",
            "direction": "high", "threshold": 0.15, "upper_cap": None, "penalty_cap": None,
            "note": "配当スコアと共有",
        },
        {
            "label": "出来高増加率", "status": "pending", "weight": 0.5,
            "unit": "倍",
            "description": "直近20日平均出来高 ÷ 過去3ヶ月平均出来高。出来高を伴う上昇は機関投資家の本格参入を示し、モメンタムの信頼性が高い。price_historyに3ヶ月分蓄積後に有効化。",
            "formula": "直近20日平均出来高 ÷ 90日前〜20日前の平均出来高",
            "good": "1.5倍以上", "warning": "出来高なき上昇は持続性に疑問",
            "direction": "high", "threshold": 1.50, "upper_cap": None, "penalty_cap": None,
            "note": None,
        },
        {
            "label": "移動平均線乖離率", "status": "todo", "weight": 1.5,
            "unit": "%",
            "description": "現在株価が25日・200日移動平均線の上位にあるかを確認。25日線上かつ200日線上＝上昇トレンド確認済み。200日線を上抜けた「ゴールデンクロス」は強力なシグナル。price_history200日分蓄積後に実装予定。",
            "formula": "（現在株価 − 200日移動平均） ÷ 200日移動平均 × 100",
            "good": "25日・200日線の上", "warning": "200日線を下回ると下降トレンド",
            "direction": "high", "threshold": 0.05, "upper_cap": None, "penalty_cap": None,
            "note": None,
        },
        {
            "label": "業績上方修正", "status": "todo", "weight": 2.0,
            "unit": "フラグ",
            "description": "直近決算での通期業績予想の上方修正有無。日本企業は保守的な業績予想を出す傾向が強く、上方修正発表後は3〜6ヶ月にわたる株価上昇が統計的に確認されている日本株固有の強力なシグナル。TDnet（適時開示情報）との連携が必要。",
            "formula": "当期通期予想EPS > 前回予想EPS の場合に1、それ以外0",
            "good": "上方修正あり（1）", "warning": "下方修正は強いマイナスシグナル",
            "direction": "high", "threshold": 1.0, "upper_cap": None, "penalty_cap": None,
            "note": "TDnet連携が必要",
        },
    ]

    return {
        "dividend": {
            "title": "配当スコア",
            "description": "高配当株の安定性・持続性・割安度を評価。連続非減配・配当性向・財務健全性が中心。",
            "indicators": dividend_indicators,
        },
        "momentum": {
            "title": "モメンタムスコア",
            "description": "株価上昇トレンドと業績加速を評価。今まさに動いている銘柄を発見するための指標。",
            "indicators": momentum_indicators,
        },
    }
