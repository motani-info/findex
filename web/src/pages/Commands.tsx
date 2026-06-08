export default function Commands() {
  const groups = [
    {
      title: "データ更新",
      color: "blue",
      commands: [
        {
          cmd: "findex update",
          desc: "日次更新（株価取得 + 再スコアリング）",
          detail: "全銘柄の最新終値をyfinanceで取得し、配当スコアを再計算してDBに保存。毎日実行推奨。所要時間: 1〜2分",
          options: [],
        },
        {
          cmd: "findex update --backfill",
          desc: "過去株価履歴を一括取得（初回・年1回）",
          detail: "price_historyに過去2年分の日次終値を保存。モメンタムの3M/12Mリターン計算に必要。所要時間: 10〜20分",
          options: [
            { flag: "--period 2y", desc: "取得期間（1y / 2y / 5y）デフォルト: 2y" },
            { flag: "--codes 7203,9433", desc: "特定銘柄のみ実行" },
          ],
        },
        {
          cmd: "findex update --quarterly",
          desc: "財務データ更新（四半期）",
          detail: "EPS・BPS・ROE・営業利益率などをAPIで再取得。fin_updated_atが90日以上前の銘柄のみ対象。",
          options: [
            { flag: "--force-all", desc: "TTL無視で全銘柄強制更新" },
          ],
        },
        {
          cmd: "findex update --dividends",
          desc: "配当履歴更新（半年）",
          detail: "連続非減配年数・10年増配率CAGRなどの配当データを再取得。div_updated_atが180日以上前の銘柄のみ対象。",
          options: [
            { flag: "--force-all", desc: "TTL無視で全銘柄強制更新" },
          ],
        },
      ],
    },
    {
      title: "配当スコア",
      color: "green",
      commands: [
        {
          cmd: "findex dividend rank",
          desc: "配当スコアランキングを表示",
          detail: "DBから即時取得（API不要）。スコア順にソートして表示。",
          options: [
            { flag: "--top 30",           desc: "表示件数（デフォルト: 30）" },
            { flag: "--market プライム",   desc: "市場でフィルタ" },
            { flag: "--sector 電気機器",   desc: "業種でフィルタ" },
            { flag: "--min-yield 0.03",   desc: "最低配当利回り（例: 3%）" },
            { flag: "--min-no-cut 10",    desc: "最低連続非減配年数" },
            { flag: "--large-cap",        desc: "大型株（5,000億円以上）" },
            { flag: "--mid-cap",          desc: "中型株（1,000〜5,000億円）" },
            { flag: "--small-cap",        desc: "小型株（1,000億円未満）" },
            { flag: "--max-per 20",       desc: "PER上限" },
            { flag: "--out result.csv",   desc: "CSV出力" },
          ],
        },
        {
          cmd: "findex dividend check 7203",
          desc: "単一銘柄の配当スコア詳細を表示",
          detail: "指標別スコア内訳・生データを確認できる。",
          options: [],
        },
      ],
    },
    {
      title: "モメンタムスコア",
      color: "indigo",
      commands: [
        {
          cmd: "findex momentum rank",
          desc: "モメンタムランキングを表示",
          detail: "price_history + stock_fundamentals からリアルタイム計算。配当スコアとは独立。",
          options: [
            { flag: "--top 30",             desc: "表示件数（デフォルト: 30）" },
            { flag: "--market プライム",     desc: "市場でフィルタ" },
            { flag: "--sector 電気機器",     desc: "業種でフィルタ" },
            { flag: "--min-div-score 70",   desc: "配当スコア下限（オプション）" },
            { flag: "--large-cap",          desc: "大型株フィルタ" },
          ],
        },
        {
          cmd: "findex momentum check 7203",
          desc: "単一銘柄のモメンタムスコア詳細を表示",
          detail: "3M/12Mリターン・52週高値比率・売上成長率など指標別スコアを確認。",
          options: [],
        },
      ],
    },
    {
      title: "サーバー・セットアップ",
      color: "gray",
      commands: [
        {
          cmd: "findex serve",
          desc: "GUIサーバーを起動（http://localhost:8080）",
          detail: "FastAPI + React のローカルGUIを起動する。",
          options: [
            { flag: "--port 8080", desc: "ポート番号（デフォルト: 8080）" },
          ],
        },
        {
          cmd: "findex setup",
          desc: "APIキーを対話式に設定",
          detail: "~/.findex/config.toml に保存（chmod 600）。",
          options: [],
        },
      ],
    },
  ]

  const colorMap: Record<string, { border: string; header: string; title: string; badge: string }> = {
    blue:   { border: "border-blue-200",   header: "bg-blue-50",   title: "text-blue-700",   badge: "bg-blue-100 text-blue-700" },
    green:  { border: "border-green-200",  header: "bg-green-50",  title: "text-green-700",  badge: "bg-green-100 text-green-700" },
    indigo: { border: "border-indigo-200", header: "bg-indigo-50", title: "text-indigo-700", badge: "bg-indigo-100 text-indigo-700" },
    gray:   { border: "border-gray-200",   header: "bg-gray-50",   title: "text-gray-600",   badge: "bg-gray-100 text-gray-600" },
  }

  const setupSteps = [
    {
      step: 1,
      cmd: "findex update --stocks",
      time: "1〜2分",
      purpose: "銘柄マスター取得",
      detail: "取引所に上場している全銘柄のコード・名称・市場・業種をDBに登録する。以降のすべての更新コマンドはこのマスターデータを前提とする。",
      dependency: null,
    },
    {
      step: 2,
      cmd: "findex update --quarterly",
      time: "20〜60分",
      purpose: "財務データ取得",
      detail: "EPS・BPS・ROE・営業利益率・売上成長率などをAPIで全銘柄分取得してDBに保存する。配当スコアおよびモメンタムスコアの計算に必須。",
      dependency: "ステップ1（銘柄マスター）が必要",
    },
    {
      step: 3,
      cmd: "findex update",
      time: "1〜2分",
      purpose: "株価取得・スコア計算",
      detail: "全銘柄の最新終値を取得し、財務データをもとに配当スコアを計算してDBに保存する。GUI・ランキングはこのスコアを参照する。",
      dependency: "ステップ2（財務データ）が必要",
    },
    {
      step: 4,
      cmd: "findex update --backfill --period 2y",
      time: "10〜20分",
      purpose: "過去株価履歴取得",
      detail: "過去2年分の日次終値をprice_historyに一括保存する。モメンタムスコアの3ヶ月・12ヶ月リターンおよび52週高値比率の計算に必要。",
      dependency: "ステップ1（銘柄マスター）が必要",
    },
    {
      step: 5,
      cmd: "findex update --dividends",
      time: "30分〜",
      purpose: "配当履歴取得",
      detail: "連続非減配年数・10年増配率CAGRなど配当関連データを全銘柄分取得してDBに保存する。配当スコアの精度向上に寄与する。",
      dependency: "ステップ1（銘柄マスター）が必要",
    },
    {
      step: 6,
      cmd: "findex serve",
      time: "即時",
      purpose: "GUI起動",
      detail: "http://localhost:8080 でFastAPI + React のローカルGUIを起動する。ランキング閲覧・銘柄検索・スコア詳細確認が可能になる。",
      dependency: "ステップ3（スコア計算）完了後が推奨",
    },
  ]

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-800">CLIコマンドリスト</h1>
        <p className="text-sm text-gray-500 mt-1">
          仮想環境を有効化してから実行: <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">source .venv/bin/activate</code>
        </p>
      </div>

      {/* 初回セットアップ */}
      <section>
        <h2 className="text-sm font-bold uppercase tracking-wide mb-3 text-orange-600">
          初回セットアップ（この順番で実行）
        </h2>
        <div className="bg-orange-50 border border-orange-200 rounded-xl overflow-hidden shadow-sm">
          <div className="px-5 py-3 bg-orange-100 border-b border-orange-200">
            <p className="text-xs text-orange-800 font-medium">
              初めて使うときはこの順番で実行してください。各ステップは前のステップの完了を前提とします。
            </p>
          </div>
          <div className="divide-y divide-orange-100">
            {setupSteps.map(s => (
              <div key={s.step} className="px-5 py-4 flex gap-4">
                <div className="shrink-0 w-7 h-7 rounded-full bg-orange-200 text-orange-800 text-xs font-bold flex items-center justify-center">
                  {s.step}
                </div>
                <div className="space-y-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="text-sm font-bold text-gray-800 font-mono">{s.cmd}</code>
                    <span className="bg-orange-100 text-orange-700 text-xs px-2 py-0.5 rounded font-medium">{s.purpose}</span>
                    <span className="text-xs text-gray-400">約 {s.time}</span>
                  </div>
                  <p className="text-xs text-gray-600">{s.detail}</p>
                  {s.dependency && (
                    <p className="text-xs text-orange-600 font-medium">依存: {s.dependency}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {groups.map(group => {
        const c = colorMap[group.color]
        return (
          <section key={group.title}>
            <h2 className={`text-sm font-bold uppercase tracking-wide mb-3 ${c.title}`}>
              {group.title}
            </h2>
            <div className="space-y-3">
              {group.commands.map(cmd => (
                <div key={cmd.cmd} className={`bg-white border ${c.border} rounded-xl overflow-hidden shadow-sm`}>
                  <div className={`px-5 py-3 ${c.header} border-b ${c.border}`}>
                    <div className="flex items-start gap-3">
                      <code className="text-sm font-bold text-gray-800 font-mono">{cmd.cmd}</code>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">{cmd.desc}</p>
                  </div>
                  <div className="px-5 py-3 space-y-2">
                    <p className="text-xs text-gray-600">{cmd.detail}</p>
                    {cmd.options.length > 0 && (
                      <div className="space-y-1 mt-2">
                        {cmd.options.map(opt => (
                          <div key={opt.flag} className="flex items-start gap-3 text-xs">
                            <code className={`shrink-0 px-2 py-0.5 rounded font-mono ${c.badge}`}>{opt.flag}</code>
                            <span className="text-gray-500 pt-0.5">{opt.desc}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )
      })}

      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-xs text-amber-800 space-y-1">
        <p className="font-semibold">📌 推奨運用スケジュール</p>
        <p>毎日: <code className="bg-white px-1 rounded">findex update</code> — 株価・スコア更新</p>
        <p>四半期: <code className="bg-white px-1 rounded">findex update --quarterly</code> — 財務データ更新</p>
        <p>半年: <code className="bg-white px-1 rounded">findex update --dividends</code> — 配当履歴更新</p>
        <p>初回のみ: <code className="bg-white px-1 rounded">findex update --backfill</code> — 過去2年分の株価一括取得</p>
      </div>
    </div>
  )
}
