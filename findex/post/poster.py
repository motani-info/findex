"""X(Twitter) 投稿（Playwright・セッション再利用・画像添付対応）。

旧 x_poster をベースに「画像主役型(B)」のため**画像添付**を追加。
- 初回/失効時のみヘッドフルでログイン→ ~/.findex/x_session.json に保存
- 以降は保存セッションで投稿（既定 headless）
- 投稿の可否（品質ゲート）は呼び出し側で判定済みの前提。ここは送信機構のみ。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import config

SESSION_FILE = config.X_SESSION_PATH


def _screenshot(page, name: str) -> None:
    path = config.FINDEX_HOME / "shots" / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path))


def _do_login(p, email: str, password: str) -> bool:
    browser = p.chromium.launch(
        channel="chrome", headless=False,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(locale="ja-JP", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    try:
        page.goto("https://x.com/login")
        time.sleep(2)
        page.locator('input[name="username_or_email"]').first.fill(email)
        page.keyboard.press("Enter")
        time.sleep(2)
        page.locator('input[name="password"]').first.fill(password)
        page.keyboard.press("Enter")
        try:
            page.wait_for_url("**/home", timeout=15000)
        except Exception:
            pass
        time.sleep(2)
        if "home" not in page.url:
            _screenshot(page, "x_login_fail")
            print(f"❌ ログイン失敗 URL={page.url}")
            return False
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(SESSION_FILE))
        print(f"✅ ログイン成功・セッション保存: {SESSION_FILE}")
        return True
    finally:
        ctx.close()
        browser.close()


def post_to_x(body: str, images: list[Path] | None = None, *, headless: bool = True) -> bool:
    """本文＋画像（最大4枚）を1ツイートとして投稿する。"""
    from dotenv import load_dotenv
    from playwright.sync_api import sync_playwright

    load_dotenv()
    images = images or []
    email = os.getenv("X_EMAIL", "")
    password = os.getenv("X_PASSWORD", "")

    with sync_playwright() as p:
        if not SESSION_FILE.exists():
            print("   セッションなし → ヘッドフルでログインします...")
            if not _do_login(p, email, password):
                return False

        browser = p.chromium.launch(
            channel="chrome", headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="ja-JP", viewport={"width": 1280, "height": 900},
            storage_state=str(SESSION_FILE),
        )
        page = ctx.new_page()
        try:
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            if "home" not in page.url:
                print("   セッション切れ → 再ログインします...")
                ctx.close(); browser.close()
                SESSION_FILE.unlink(missing_ok=True)
                if not _do_login(p, email, password):
                    return False
                browser = p.chromium.launch(
                    channel="chrome", headless=headless,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                )
                ctx = browser.new_context(
                    locale="ja-JP", viewport={"width": 1280, "height": 900},
                    storage_state=str(SESSION_FILE),
                )
                page = ctx.new_page()

            page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            page.evaluate("""
                window.__maskObserver = new MutationObserver(() => {
                    document.querySelectorAll('[data-testid=mask]').forEach(e => e.remove());
                });
                window.__maskObserver.observe(document.body, {childList: true, subtree: true});
            """)

            page.locator('[data-testid="tweetTextarea_0"]').first.wait_for(timeout=10000)
            page.locator('[data-testid="tweetTextarea_0"]').first.click()
            time.sleep(0.5)
            page.keyboard.type(body, delay=12)
            time.sleep(1)

            # 画像添付（隠れた file input に直接セット）
            if images:
                file_input = page.locator('input[type="file"][data-testid="fileInput"]').first
                file_input.set_input_files([str(p2) for p2 in images])
                # アップロード完了（プレビューのremoveボタン）を待つ
                try:
                    page.locator('[aria-label*="削除"], [data-testid="removeMedia"]').first.wait_for(timeout=20000)
                except Exception:
                    time.sleep(5)
                time.sleep(1)

            _screenshot(page, "x_before_post")
            page.locator('[data-testid="tweetButton"]').last.wait_for(timeout=8000)
            page.locator('[data-testid="tweetButton"]').last.click()
            time.sleep(4)
            _screenshot(page, "x_after_post")
            print("✅ 投稿完了")
            return True
        except Exception as e:
            _screenshot(page, "x_error")
            print(f"❌ エラー: {e}")
            return False
        finally:
            ctx.close()
            browser.close()


def save_login() -> bool:
    """セッションを強制リセットして再ログイン。"""
    from dotenv import load_dotenv
    from playwright.sync_api import sync_playwright
    load_dotenv()
    SESSION_FILE.unlink(missing_ok=True)
    with sync_playwright() as p:
        return _do_login(p, os.getenv("X_EMAIL", ""), os.getenv("X_PASSWORD", ""))
