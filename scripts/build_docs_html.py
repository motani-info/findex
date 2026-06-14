"""docs/*.md → docs/html/*.html（人間レビュー用の整形HTML）。

使い方:
    uv run python scripts/build_docs_html.py
    # 出力を開く: open docs/html/index.html

再現可能。docs を編集したら再実行する。外部CDN非依存（オフラインで開ける）。
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "html"

# 変換対象: (入力md, 出力html, タイトル, バッジ)
PAGES = [
    (DOCS / "PROGRESS.md", "progress.html", "進捗ダッシュボード", "★ Progress"),
    (DOCS / "design" / "00-charter-and-data-integrity.md", "charter.html", "ノーススター：定款とデータ完全性", "★ North Star"),
    (DOCS / "PROJECT-LOG.md", "project-log.html", "プロジェクトログ（フェーズ記録）", "Log"),
    (DOCS / "IMPLEMENTATION-PLAN.md", "implementation-plan.html", "実装フェーズ計画", "★ Plan"),
    (DOCS / "design" / "02-data-integrity-framework.md", "data-integrity-framework.html", "D2：データ完全性フレームワーク", "Design"),
    (DOCS / "design" / "02_5-feasibility-findings.md", "feasibility-findings.html", "D2.5：取得可能性スタディ実測", "Design"),
    (DOCS / "design" / "02_6-data-limits-and-impact.md", "data-limits-and-impact.html", "D2.6：取得限界と評価軸への影響", "Design"),
    (DOCS / "design" / "02_7-result-override-layer.md", "result-override-layer.html", "D2.7：結果補正レイヤ", "Design"),
    (DOCS / "design" / "04-indicator-system.md", "indicator-system.html", "D4：指標システム仕様", "Design"),
    (DOCS / "design" / "04_5-indicator-calibration.md", "indicator-calibration.html", "D4.5：指標較正（v4提案）", "Design"),
    (DOCS / "design" / "06-verification-strategy.md", "verification-strategy.html", "D6：多フィールド検証戦略", "Design"),
    (DOCS / "design" / "analysis-angles.md", "analysis-angles.html", "分析切り口カタログ", "Angles"),
    (DOCS / "requirements.md", "requirements.html", "要件定義書 v2", "Requirements"),
    (DOCS / "design" / "data-model.md", "data-model.html", "テーブル定義（データモデル）", "Design"),
    (DOCS / "design" / "data-workflow.md", "data-workflow.html", "データワークフロー", "Design"),
    (DOCS / "design" / "pre2000-data.md", "pre2000-data.html", "2000年問題（データ完全性の一事例）", "Design"),
]

CSS = """
:root{
  --bg:#0f1115; --panel:#161922; --ink:#e6e8ee; --muted:#9aa3b2;
  --line:#272c38; --accent:#6ea8fe; --accent2:#7ee0c0; --warn:#ffc24b;
  --code-bg:#0b0d12; --th:#1d2230;
}
@media (prefers-color-scheme: light){
  :root{ --bg:#f7f8fa; --panel:#ffffff; --ink:#1b1f27; --muted:#5b6472;
    --line:#e3e7ee; --accent:#2563eb; --accent2:#0f9d77; --warn:#9a6700;
    --code-bg:#f1f3f7; --th:#eef1f6; }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",Segoe UI,sans-serif;
  line-height:1.75;font-size:15px;}
.layout{display:grid;grid-template-columns:280px 1fr;min-height:100vh}
nav.side{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;
  background:var(--panel);border-right:1px solid var(--line);padding:22px 18px}
nav.side h1{font-size:15px;margin:0 0 4px;letter-spacing:.02em}
nav.side .sub{color:var(--muted);font-size:12px;margin-bottom:18px}
nav.side .doclinks a{display:block;padding:8px 10px;border-radius:8px;color:var(--ink);
  text-decoration:none;font-size:13px;margin-bottom:4px;border:1px solid transparent}
nav.side .doclinks a:hover{background:var(--th)}
nav.side .doclinks a.active{border-color:var(--line);background:var(--th);font-weight:600}
nav.side .toc{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}
nav.side .toc a{display:block;color:var(--muted);text-decoration:none;font-size:12.5px;
  padding:3px 0;border-left:2px solid transparent;padding-left:10px}
nav.side .toc a:hover{color:var(--ink)}
nav.side .toc a.l3{padding-left:22px;font-size:12px}
main{padding:48px 56px;max-width:980px}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:var(--accent2);border:1px solid var(--line);
  border-radius:999px;padding:3px 10px;margin-bottom:14px}
h1,h2,h3{line-height:1.3}
h1{font-size:28px;margin:.2em 0 .6em}
h2{font-size:21px;margin:1.8em 0 .6em;padding-bottom:.3em;border-bottom:1px solid var(--line)}
h3{font-size:16.5px;margin:1.4em 0 .5em;color:var(--accent)}
a{color:var(--accent)}
hr{border:none;border-top:1px solid var(--line);margin:2em 0}
code{background:var(--code-bg);padding:.12em .4em;border-radius:5px;font-size:.88em;
  font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace}
pre{background:var(--code-bg);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;overflow:auto}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:13.5px;
  border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{border:1px solid var(--line);padding:8px 12px;text-align:left;vertical-align:top}
th{background:var(--th);font-weight:700}
tr:nth-child(even) td{background:rgba(127,127,127,.05)}
blockquote{margin:1.2em 0;padding:.6em 1.1em;border-left:3px solid var(--warn);
  background:rgba(255,194,75,.08);color:var(--ink);border-radius:0 8px 8px 0}
.toolbar{margin-bottom:8px;color:var(--muted);font-size:12px}
ul,ol{padding-left:1.4em}
li{margin:.2em 0}
"""

TOC_RE = re.compile(r'<(h2|h3)[^>]*id="([^"]+)"[^>]*>(.*?)</\1>', re.S)
TAG_RE = re.compile(r"<[^>]+>")

# md stem → output html name (for link rewriting)
MD_TO_HTML: dict[str, str] = {}


def build_toc(html: str) -> str:
    items = []
    for level, anchor, text in TOC_RE.findall(html):
        label = TAG_RE.sub("", text).strip()
        cls = "l3" if level == "h3" else "l2"
        items.append(f'<a class="{cls}" href="#{anchor}">{label}</a>')
    return "\n".join(items)


def doc_links(active: str) -> str:
    out = ['<a href="index.html">← 目次</a>']
    for _src, html_name, title, _badge in PAGES:
        cls = "active" if html_name == active else ""
        out.append(f'<a class="{cls}" href="{html_name}">{title}</a>')
    return "\n".join(out)


def rewrite_links(html: str) -> str:
    # 相対 .md リンクを output html name に張り替える（カスタム名対応）
    def repl(m):
        href = m.group(1)
        if href.startswith("http") or "#" in href.split("/")[-1][:1]:
            return m.group(0)
        if href.endswith(".md"):
            stem = Path(href).stem
            out_name = MD_TO_HTML.get(stem, stem + ".html")
            return f'href="{out_name}"'
        return m.group(0)

    return re.sub(r'href="([^"]+\.md)"', repl, html)


_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_ITALIC_RE = re.compile(r'\*([^*]+)\*')


def strip_md(text: str) -> str:
    text = _MD_LINK_RE.sub(r'\1', text)
    text = _BOLD_RE.sub(r'\1', text)
    text = _ITALIC_RE.sub(r'\1', text)
    return text


def extract_blurb(src: Path) -> str:
    text = src.read_text(encoding="utf-8")
    for para in text.split("\n\n"):
        p = para.replace("\n", " ").strip()
        if not p:
            continue
        if p.startswith("#") or p.startswith("**") or re.match(r"^-{3,}$", p):
            continue
        return strip_md(p)[:160]
    return ""


PAGE_TMPL = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — findex</title><style>{css}</style></head>
<body><div class="layout">
<nav class="side">
  <h1>findex docs</h1><div class="sub">v2 再構築 / レビュー用</div>
  <div class="doclinks">{links}</div>
  <div class="toc">{toc}</div>
</nav>
<main>
  <div class="badge">{badge}</div>
  {body}
</main></div></body></html>"""

INDEX_TMPL = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>findex docs</title><style>{css}</style></head>
<body><div class="layout">
<nav class="side"><h1>findex docs</h1><div class="sub">v2 再構築 / レビュー用</div>
<div class="doclinks">{links}</div></nav>
<main><div class="badge">Index</div>
<h1>findex v2 設計ドキュメント</h1>
<p>日本株スコアリング・ランキングツールの再構築。全銘柄・全フィールドのデータ完全性を土台に、進化し続ける独自指標で多角的に分析し、Xユーザーの興味を引く切り口で投稿し続ける。</p>
{cards}
<hr><p style="color:var(--muted);font-size:12px">このHTMLは <code>scripts/build_docs_html.py</code> で <code>docs/*.md</code> から生成。docs編集後に再実行する。</p>
</main></div></body></html>"""


def main() -> None:
    # Build stem→html mapping so rewrite_links knows custom output names
    for src, html_name, *_ in PAGES:
        MD_TO_HTML[src.stem] = html_name

    OUT.mkdir(parents=True, exist_ok=True)
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list", "codehilite"],
        extension_configs={"toc": {"permalink": False}, "codehilite": {"noclasses": True}},
    )
    cards = []
    for src, html_name, title, badge in PAGES:
        md.reset()
        body = md.convert(src.read_text(encoding="utf-8"))
        body = rewrite_links(body)
        toc = build_toc(body)
        html = PAGE_TMPL.format(title=title, css=CSS, links=doc_links(html_name), toc=toc, badge=badge, body=body)
        (OUT / html_name).write_text(html, encoding="utf-8")
        blurb = extract_blurb(src)
        cards.append(
            f'<h3 style="margin-top:1.4em"><a href="{html_name}">{title}</a> '
            f'<span style="color:var(--muted);font-weight:400;font-size:13px">[{badge}]</span></h3>'
            f'<p style="color:var(--muted)">{blurb[:160]}</p>'
        )
        print(f"  ✓ {html_name}")

    (OUT / "index.html").write_text(
        INDEX_TMPL.format(css=CSS, links=doc_links("index.html"), cards="\n".join(cards)),
        encoding="utf-8",
    )
    print(f"  ✓ index.html\n出力: {OUT}")


if __name__ == "__main__":
    main()
