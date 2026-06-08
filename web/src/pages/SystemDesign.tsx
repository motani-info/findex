import { useEffect, useState } from 'react'
import axios from 'axios'

type Column = { name: string; type: string; desc: string }
type Table  = { name: string; role: string; updated: string; columns: Column[] }
type Endpoint = { method: string; path: string; desc: string }
type EndpointGroup = { group: string; color: string; endpoints: Endpoint[] }

type DesignData = { tables: Table[]; endpoints: EndpointGroup[] }
type StatsData  = {
  stocks: number
  price_history: { records: number; codes: number; latest_date: string; oldest_date: string }
  stock_fundamentals: number
  scores: { records: number; codes: number; latest_date: string }
}

const METHOD_COLOR: Record<string, string> = {
  GET:  'bg-green-100 text-green-700',
  POST: 'bg-blue-100  text-blue-700',
  PUT:  'bg-yellow-100 text-yellow-700',
  DELETE: 'bg-red-100 text-red-700',
}

const GROUP_COLOR: Record<string, string> = {
  green:  'border-green-200 bg-green-50',
  blue:   'border-blue-200  bg-blue-50',
  purple: 'border-purple-200 bg-purple-50',
  amber:  'border-amber-200  bg-amber-50',
  gray:   'border-gray-200   bg-gray-50',
  slate:  'border-slate-200  bg-slate-50',
}
const GROUP_TITLE_COLOR: Record<string, string> = {
  green:  'text-green-700',
  blue:   'text-blue-700',
  purple: 'text-purple-700',
  amber:  'text-amber-700',
  gray:   'text-gray-700',
  slate:  'text-slate-700',
}

function TableCard({ table }: { table: Table }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <button
        className="w-full text-left px-5 py-4 flex items-start justify-between hover:bg-gray-50 transition"
        onClick={() => setOpen(o => !o)}
      >
        <div>
          <div className="flex items-center gap-2">
            <code className="text-sm font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded">{table.name}</code>
            <span className="text-sm text-gray-600">{table.role}</span>
          </div>
          <p className="text-xs text-gray-400 mt-1">更新タイミング: {table.updated}</p>
        </div>
        <span className="text-gray-300 text-xs mt-1">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2 text-left w-48">カラム名</th>
                <th className="px-4 py-2 text-left w-36">型</th>
                <th className="px-4 py-2 text-left">説明</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {table.columns.map(col => (
                <tr key={col.name} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-indigo-600 text-xs">{col.name}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{col.type}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{col.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-800">{value?.toLocaleString() ?? '—'}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function SystemDesign() {
  const [design, setDesign] = useState<DesignData | null>(null)
  const [stats,  setStats]  = useState<StatsData  | null>(null)

  useEffect(() => {
    Promise.all([
      axios.get('/api/system/design'),
      axios.get('/api/system/stats'),
    ]).then(([d, s]) => {
      setDesign(d.data)
      setStats(s.data)
    })
  }, [])

  return (
    <div className="space-y-8 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-800">システム設計</h1>
        <p className="text-sm text-gray-500 mt-1">DBテーブル定義・APIエンドポイント一覧</p>
      </div>

      {/* DBサマリー */}
      {stats && (
        <section>
          <h2 className="text-base font-semibold text-gray-700 mb-3">📊 DBサマリー</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="上場銘柄数" value={stats.stocks} sub="stocks テーブル" />
            <StatCard
              label="株価履歴"
              value={`${stats.price_history.codes?.toLocaleString()} 銘柄`}
              sub={stats.price_history.oldest_date
                ? `${stats.price_history.oldest_date} 〜 ${stats.price_history.latest_date}`
                : 'データなし'}
            />
            <StatCard label="財務データ" value={stats.stock_fundamentals} sub="stock_fundamentals テーブル" />
            <StatCard
              label="配当スコア"
              value={`${stats.scores.codes?.toLocaleString()} 銘柄`}
              sub={`最終更新: ${stats.scores.latest_date ?? '—'}`}
            />
          </div>
        </section>
      )}

      {/* テーブル定義 */}
      {design && (
        <section>
          <h2 className="text-base font-semibold text-gray-700 mb-3">🗄️ テーブル定義</h2>
          <p className="text-xs text-gray-400 mb-3">行をクリックでカラム詳細を表示</p>
          <div className="space-y-3">
            {design.tables.map(t => <TableCard key={t.name} table={t} />)}
          </div>
        </section>
      )}

      {/* データフロー */}
      <section>
        <h2 className="text-base font-semibold text-gray-700 mb-3">🔄 データフロー</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            <div className="space-y-2">
              <div className="font-semibold text-gray-600 text-xs uppercase tracking-wide">取得（CLI）</div>
              <div className="bg-gray-50 rounded-lg p-3 space-y-1.5 text-xs text-gray-700">
                <div><code className="text-indigo-600">findex update</code><br/>株価取得・日次再スコアリング</div>
                <div><code className="text-indigo-600">findex update --backfill</code><br/>過去2年分の株価一括取得（初回）</div>
                <div><code className="text-indigo-600">findex update --quarterly</code><br/>財務データ更新（四半期）</div>
                <div><code className="text-indigo-600">findex update --dividends</code><br/>配当履歴更新（半年）</div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="font-semibold text-gray-600 text-xs uppercase tracking-wide">保存先（DB）</div>
              <div className="bg-gray-50 rounded-lg p-3 space-y-1.5 text-xs text-gray-700">
                <div><code className="text-indigo-600">price_history</code><br/>日次終値（全銘柄共通）</div>
                <div><code className="text-indigo-600">stock_fundamentals</code><br/>財務・配当データ（全銘柄共通）</div>
                <div><code className="text-indigo-600">scores</code><br/>配当スコア計算結果</div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="font-semibold text-gray-600 text-xs uppercase tracking-wide">表示（API → UI）</div>
              <div className="bg-gray-50 rounded-lg p-3 space-y-1.5 text-xs text-gray-700">
                <div><code className="text-indigo-600">配当スコア</code><br/>scores テーブルから取得</div>
                <div><code className="text-indigo-600">モメンタムスコア</code><br/>price_history + stock_fundamentals からリアルタイム計算</div>
                <div><code className="text-indigo-600">配当はモメンタムに無関係</code><br/>スコアはそれぞれ独立</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* APIエンドポイント */}
      {design && (
        <section>
          <h2 className="text-base font-semibold text-gray-700 mb-3">🔌 APIエンドポイント</h2>
          <div className="space-y-4">
            {design.endpoints.map(group => (
              <div
                key={group.group}
                className={`border rounded-xl overflow-hidden ${GROUP_COLOR[group.color] ?? 'border-gray-200 bg-gray-50'}`}
              >
                <div className="px-4 py-2 border-b border-gray-100">
                  <span className={`text-xs font-bold uppercase tracking-wide ${GROUP_TITLE_COLOR[group.color] ?? 'text-gray-600'}`}>
                    {group.group}
                  </span>
                </div>
                <div className="divide-y divide-gray-100">
                  {group.endpoints.map(ep => (
                    <div key={ep.path} className="flex items-start gap-3 px-4 py-3">
                      <span className={`shrink-0 text-xs font-bold px-2 py-0.5 rounded font-mono ${METHOD_COLOR[ep.method] ?? ''}`}>
                        {ep.method}
                      </span>
                      <div className="min-w-0">
                        <code className="text-xs text-gray-700 break-all">{ep.path}</code>
                        <p className="text-xs text-gray-500 mt-0.5">{ep.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
