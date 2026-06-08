import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getStats, getDividendRank, getMomentumRank } from '../api'

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 text-center shadow-sm">
      <div className="text-2xl font-bold text-indigo-600">{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  )
}

function MiniTable({ items, type }: { items: any[]; type: 'dividend' | 'momentum' }) {
  const scoreKey = type === 'dividend' ? 'score' : 'momentum_score'
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-400 border-b">
          <th className="text-left py-1">#</th>
          <th className="text-left py-1">コード</th>
          <th className="text-left py-1">銘柄名</th>
          <th className="text-right py-1">スコア</th>
          {type === 'dividend' && <th className="text-right py-1">利回り</th>}
          {type === 'momentum' && <th className="text-right py-1">3M</th>}
        </tr>
      </thead>
      <tbody>
        {items.map((r, i) => (
          <tr key={r.code} className="border-b border-gray-50 hover:bg-gray-50">
            <td className="py-1 text-gray-400">{i + 1}</td>
            <td className="py-1">
              <Link to={`/stock/${r.code}`} className="text-indigo-600 hover:underline font-mono">{r.code}</Link>
            </td>
            <td className="py-1 truncate max-w-[120px]">{r.name}</td>
            <td className="py-1 text-right font-semibold">{r[scoreKey]?.toFixed(1)}</td>
            {type === 'dividend' && <td className="py-1 text-right text-green-600">{r.div_yield ? `${r.div_yield}%` : '-'}</td>}
            {type === 'momentum' && <td className="py-1 text-right text-blue-600">{r.ret_3m != null ? `${r.ret_3m > 0 ? '+' : ''}${r.ret_3m}%` : '-'}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<any>(null)
  const [divTop, setDivTop] = useState<any[]>([])
  const [momTop, setMomTop] = useState<any[]>([])
  const [updating, setUpdating] = useState(false)
  const [updateLog, setUpdateLog] = useState<string[]>([])

  useEffect(() => {
    getStats().then(setStats)
    getDividendRank({ top: 10 }).then(d => setDivTop(d.items))
    getMomentumRank({ top: 10 }).then(d => setMomTop(d.items))
  }, [])

  const runUpdate = async () => {
    setUpdating(true)
    setUpdateLog([])
    const res = await fetch('/api/update/run', { method: 'POST' })
    const reader = res.body!.getReader()
    const dec = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = dec.decode(value)
      const lines = text.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6))
      setUpdateLog(prev => [...prev, ...lines])
    }
    setUpdating(false)
    getStats().then(setStats)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">ダッシュボード</h1>
        <button
          onClick={runUpdate}
          disabled={updating}
          className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition"
        >
          {updating ? '更新中...' : '今すぐ更新'}
        </button>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="登録銘柄" value={stats.stock_count?.toLocaleString()} />
          <StatCard label="スコア済み" value={stats.score_count?.toLocaleString()} />
          <StatCard label="最終更新" value={stats.last_updated || '-'} />
          <StatCard label="株価履歴(日)" value={stats.price_days} />
          <StatCard label="配当レコード" value={stats.div_records?.toLocaleString()} />
        </div>
      )}

      {/* Update log */}
      {updateLog.length > 0 && (
        <div className="bg-gray-900 text-green-400 rounded-lg p-4 text-xs font-mono max-h-40 overflow-y-auto">
          {updateLog.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      )}

      {/* Rankings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-gray-700">配当スコア TOP10</h2>
            <Link to="/dividend" className="text-xs text-indigo-500 hover:underline">全件 →</Link>
          </div>
          <MiniTable items={divTop} type="dividend" />
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-gray-700">モメンタム TOP10</h2>
            <Link to="/momentum" className="text-xs text-indigo-500 hover:underline">全件 →</Link>
          </div>
          <MiniTable items={momTop} type="momentum" />
        </div>
      </div>
    </div>
  )
}
