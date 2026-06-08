"""scores.raw_json → stock_fundamentals へ一括移行。
eps/bps/shares/annual_div が raw_json にない場合は
yf.Ticker.info（dividendRate, trailingEps, bookValue, sharesOutstanding）で補完。
"""
import json
import time
import traceback
from findex.db import get_db, upsert_fundamentals
import yfinance as yf


def main():
    conn = get_db()

    # Step 1: raw_json から取れるフィールドを移行
    rows = conn.execute("""
        SELECT s.code, s.raw_json, s.scored_at
        FROM scores s
        WHERE (s.code, s.scored_at) IN (
            SELECT code, MAX(scored_at) FROM scores GROUP BY code
        )
    """).fetchall()
    print(f"Step1: raw_json移行対象 {len(rows)}件", flush=True)

    migrated = 0
    for code, raw_json_str, scored_at in rows:
        if not raw_json_str:
            continue
        raw = json.loads(raw_json_str)
        data = {k: raw.get(k) for k in [
            "equity_ratio", "debt_to_equity", "roe", "operating_margin",
            "eps_growth_5y", "revenue_growth_5y_cagr", "roic_minus_wacc",
            "fcf_payout_coverage", "retained_earnings_div_ratio", "payout_ratio",
            "consecutive_no_cut_years", "consecutive_dividend_growth_years",
            "dividend_growth_5y_cagr", "dividend_growth_10y_cagr",
            "dividend_reliability", "dividend_cut_count_20y",
        ]}
        data["annual_div"] = raw.get("annual_div_per_share") or raw.get("annual_div")
        data["eps"]    = raw.get("eps")
        data["bps"]    = raw.get("bps")
        data["shares"] = raw.get("shares")
        data["fin_updated_at"] = scored_at
        data["div_updated_at"] = scored_at
        upsert_fundamentals(conn, code, data)
        migrated += 1
        if migrated % 500 == 0:
            conn.commit()
            print(f"  Step1: {migrated}件...", flush=True)

    conn.commit()
    print(f"Step1完了: {migrated}件", flush=True)

    # Step 2: eps/shares/annual_div 欠損を yf.Ticker.info で補完
    missing = conn.execute(
        "SELECT code FROM stock_fundamentals "
        "WHERE eps IS NULL OR shares IS NULL OR annual_div IS NULL"
    ).fetchall()
    targets = [r[0] for r in missing]
    print(f"\nStep2: info補完対象 {len(targets)}件...", flush=True)

    patched = failed = 0
    for i, code in enumerate(targets):
        try:
            info = yf.Ticker(f"{code}.T").info
            data = {}
            eps = info.get("trailingEps") or info.get("forwardEps")
            if eps and float(eps) != 0:
                data["eps"] = float(eps)
            bps = info.get("bookValue")
            if bps:
                data["bps"] = float(bps)
            shares = info.get("sharesOutstanding")
            if shares:
                data["shares"] = float(shares)
            div_rate = info.get("dividendRate")
            if div_rate and float(div_rate) > 0:
                data["annual_div"] = float(div_rate)

            if data:
                upsert_fundamentals(conn, code, data)
                patched += 1
            else:
                failed += 1  # データなし（無配当・上場廃止候補など）

        except Exception as e:
            failed += 1

        if (i + 1) % 200 == 0:
            conn.commit()
            elapsed_min = (i + 1) * 0.2 / 60
            eta_min = (len(targets) - i - 1) * 0.2 / 60
            print(
                f"  Step2: [{i+1}/{len(targets)}] "
                f"patched={patched} failed={failed} "
                f"経過{elapsed_min:.1f}分 残{eta_min:.1f}分",
                flush=True,
            )
        time.sleep(0.2)

    conn.commit()

    # 最終確認
    total   = conn.execute("SELECT COUNT(*) FROM stock_fundamentals").fetchone()[0]
    no_eps  = conn.execute("SELECT COUNT(*) FROM stock_fundamentals WHERE eps IS NULL").fetchone()[0]
    no_div  = conn.execute("SELECT COUNT(*) FROM stock_fundamentals WHERE annual_div IS NULL").fetchone()[0]
    no_shr  = conn.execute("SELECT COUNT(*) FROM stock_fundamentals WHERE shares IS NULL").fetchone()[0]

    print(f"\n✅ 移行完了")
    print(f"   stock_fundamentals: {total}件")
    print(f"   EPS欠損: {no_eps}件  annual_div欠損: {no_div}件  shares欠損: {no_shr}件")

    samples = conn.execute("""
        SELECT sf.code, st.name, sf.eps, sf.bps, sf.shares, sf.annual_div,
               sf.consecutive_no_cut_years
        FROM stock_fundamentals sf
        JOIN stocks st ON sf.code = st.code
        WHERE sf.eps IS NOT NULL AND sf.annual_div IS NOT NULL
        ORDER BY sf.consecutive_no_cut_years DESC NULLS LAST
        LIMIT 5
    """).fetchall()
    print("\nサンプル（連続非減配上位・EPS/配当あり）:")
    for r in samples:
        print(f"  {r[0]} {r[1]}: EPS={r[2]} BPS={r[3]} "
              f"shares={r[4] and f'{r[4]/1e6:.1f}M'} 配当={r[5]}円 非減配={r[6]}年")

    conn.close()


if __name__ == "__main__":
    main()
