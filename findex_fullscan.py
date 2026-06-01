import time
from findex.fetcher.master import fetch_stock_master
from findex.fetcher.fetch_all import fetch_all
from findex.scorer.engine import load_rules, score
from findex.output.display import save_csv
from pathlib import Path
import pandas as pd

t_total = time.time()

master = fetch_stock_master()
master = master[~master['market'].str.contains('ETF|ETN|REIT|インフラ', na=False)]
total = len(master)
print(f'全銘柄: {total}件', flush=True)

# 全市場を一括スキャン
all_data = fetch_all(master['code'].tolist(), delay=0.3)

df = master.merge(all_data, on='code', how='left')
rules  = load_rules(Path('rules.yaml'))
ranked = score(df, rules)
save_csv(ranked, '/tmp/findex_all.csv')

elapsed = time.time() - t_total
zero = (ranked.total_score == 0).sum()
print(f'=== 全市場スキャン完了 ===')
print(f'処理時間: {elapsed:.0f}秒 | 対象: {total}件 | スコア0: {zero}件')
print(f'スコア分布: min={ranked.total_score.min():.1f} mean={ranked.total_score.mean():.1f} max={ranked.total_score.max():.1f}')
print()
print('=== TOP 30 ===')
print(ranked[['code','name','market','sector','total_score']].head(30).to_string(index=False))
