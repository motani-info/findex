"""HTML→PNG 画像化（D5・画像主役型投稿の証拠画像を生成）。

X発信の主戦術は「本文＝フック / 画像＝データ」。ランキング表やチャートを
ローカルHTMLで組み、Playwright headless で要素単位のスクリーンショットを撮る。
これにより画像生成層は report.py（閲覧用サイト）と同じHTML資産を共有する。
"""
from __future__ import annotations

from pathlib import Path


def render_html_to_png(html: str, out_path: Path, *, selector: str = ".card",
                       width: int = 1000, scale: int = 2) -> Path:
    """self-contained な HTML を描画し、selector 要素を PNG に切り出す。

    - width: ビューポート幅（カードの最大幅に合わせる）
    - scale: device_scale_factor（2 で Retina 相当の高精細）
    - selector が見つからなければページ全体を撮る（フォールバック）
    """
    from playwright.sync_api import sync_playwright

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            locale="ja-JP",
            viewport={"width": width, "height": 800},
            device_scale_factor=scale,
        )
        page = ctx.new_page()
        try:
            page.set_content(html, wait_until="networkidle")
            el = page.query_selector(selector)
            if el is not None:
                el.screenshot(path=str(out_path))
            else:
                page.screenshot(path=str(out_path), full_page=True)
        finally:
            ctx.close()
            browser.close()
    return out_path
