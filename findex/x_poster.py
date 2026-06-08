"""X (Twitter) 自動投稿モジュール

初回: ヘッドフルで Chrome を起動、ID/PW でログイン、セッション保存
以降: 保存済みセッションを使って headless で投稿
"""
from __future__ import annotations

import os
import time
from pathlib import Path

SESSION_FILE = Path.home() / ".findex" / "x_session.json"


def _screenshot(page, name: str) -> None:
    path = Path.home() / ".findex" / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path))


def _do_login(p, email: str, password: str) -> bool:
    """ヘッドフルで Chrome を起動してログイン→セッション保存。"""
    browser = p.chromium.launch(
        channel="chrome",
        headless=False,  # ヘッドフル固定
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
        # ホーム画面への遷移を待つ（最大15秒）
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


def post_to_x(texts: list[str], *, headless: bool = True, dry_run: bool = False, **_) -> bool:
    from dotenv import load_dotenv
    from playwright.sync_api import sync_playwright

    load_dotenv()

    if not texts:
        return False

    if dry_run:
        print("✅ [DRY RUN]")
        for i, t in enumerate(texts, 1):
            print(f"\n【投稿{i}】\n{t}")
        return True

    email = os.getenv("X_EMAIL", "")
    password = os.getenv("X_PASSWORD", "")

    with sync_playwright() as p:
        # セッションがなければヘッドフルでログイン
        if not SESSION_FILE.exists():
            print("   セッションなし → ヘッドフルでログインします...")
            if not _do_login(p, email, password):
                return False

        # セッション使って投稿
        browser = p.chromium.launch(
            channel="chrome",
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
            storage_state=str(SESSION_FILE),
        )
        page = ctx.new_page()

        try:
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            _screenshot(page, "x_home")

            # セッション切れなら再ログイン
            if "home" not in page.url:
                print("   セッション切れ → 再ログインします...")
                ctx.close()
                browser.close()
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
                page.goto("https://x.com/home")
                time.sleep(3)

            # compose ページに直接移動
            page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # MutationObserver でマスクを継続削除
            page.evaluate("""
                window.__maskObserver = new MutationObserver(() => {
                    document.querySelectorAll('[data-testid=mask]').forEach(e => e.remove());
                });
                window.__maskObserver.observe(document.body, {childList: true, subtree: true});
            """)

            # 投稿ボックス確認
            page.locator('[data-testid="tweetTextarea_0"]').first.wait_for(timeout=10000)

            # 1枚目
            page.locator('[data-testid="tweetTextarea_0"]').first.click()
            time.sleep(0.5)
            page.keyboard.type(texts[0], delay=15)
            time.sleep(1)
            print(f"   投稿1 入力完了")

            # 2枚目以降
            for idx, text in enumerate(texts[1:], 2):
                page.locator('[data-testid="addButton"]').first.wait_for(timeout=8000)
                page.locator('[data-testid="addButton"]').first.click()
                time.sleep(1.5)
                boxes = page.locator('[data-testid^="tweetTextarea_"]')
                boxes.last.wait_for(timeout=8000)
                boxes.last.click()
                time.sleep(0.5)
                page.keyboard.type(text, delay=15)
                time.sleep(1)
                print(f"   投稿{idx} 入力完了")

            _screenshot(page, "x_before_post")
            page.locator('[data-testid="tweetButton"]').last.wait_for(timeout=5000)
            page.locator('[data-testid="tweetButton"]').last.click()
            time.sleep(4)

            _screenshot(page, "x_after_post")
            print(f"✅ 投稿完了（{len(texts)}件）")
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
    email = os.getenv("X_EMAIL", "")
    password = os.getenv("X_PASSWORD", "")
    with sync_playwright() as p:
        return _do_login(p, email, password)
