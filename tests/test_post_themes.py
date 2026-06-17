"""X投稿テーマの純関数テスト（Phase6 MVP・品質ゲートの回帰防止）。"""
from findex.post.themes import _streak_body, weighted_len


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
