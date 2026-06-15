"""財務由来指標の純関数テスト（5年CAGRのスパン/外れ値/負基準ガード）。"""
from findex.derive.compute import _cagr_5y


def test_cagr_normal_5y_span():
    rows = [(2020, 100.0), (2021, 110), (2022, 120), (2023, 130), (2024, 140), (2025, 161.05)]
    v, st = _cagr_5y(rows)
    assert st == "ok"
    assert abs(v - 0.1) < 1e-4  # 100→161.05 を5年で ≒10%


def test_cagr_insufficient_span():
    # 2年しか無い→5年成長は構造的に不能
    assert _cagr_5y([(2024, 100.0), (2025, 110)]) == (None, "insufficient")


def test_cagr_negative_base():
    # 基準年が赤字/ゼロ→算出不能
    assert _cagr_5y([(2020, -5.0), (2025, 100)]) == (None, "insufficient")
    assert _cagr_5y([(2020, 0.0), (2025, 100)]) == (None, "insufficient")


def test_cagr_outlier_dropped():
    # 100→10000 は年率異常（基準年アーティファクト）→出さない
    assert _cagr_5y([(2020, 100.0), (2025, 10000)]) == (None, "insufficient")


def test_cagr_uses_closest_year_within_window():
    # 5年前ちょうどが無くても 4年スパンが取れれば算出
    rows = [(2021, 100.0), (2023, 121), (2025, 146.41)]
    v, st = _cagr_5y(rows)
    assert st == "ok"
    assert abs(v - 0.1) < 1e-4  # 100→146.41 を4年で ≒10%
