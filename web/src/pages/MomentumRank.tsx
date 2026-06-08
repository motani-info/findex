import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMomentumRank, getSectors } from '../api'

const fmtCap = (v?: number) => {
  if (!v) return '-'
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}兆`
  if (v >= 1e8)  return `${(v / 1e8).toFixed(0)}億`
  return `${v}`
}

const fmtRet = (v?: number) => v != null ? `${v > 0 ? '+' : ''}${v}%` : '-'

export default function MomentumRank() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [sectors, setSectors] = useState<string[]>([])
  const [filters, setFilters] = useState({
    top: 50, sector: '', min_div_score: '',
    large_cap: false, mid_cap: false, small_cap: false,
  })
  const [sortKey, setSortKey] = useState('momentum_score')
  const [sortAsc, setSortAsc] = useState(false)

  useEffect(() => {
    getSectors().then(d => setSectors(d.sectors))
    load()
  }, [])

  const load = () => {
    setLoading(true)
    const params: Record<string, unknown> = { top: filters.top }
    if (filters.sector)        params.sector        = filters.sector
    if (filters.min_div_score) params.min_div_score = parseFloat(filters.min_div_score)
    if (filters.large_cap)     params.large_cap     = true
    if (filters.mid_cap)       params.mid_cap       = true
    if (filters.small_cap)     params.small_cap     = true
    getMomentumRank(params).then(d => { setItems(d.items); setLoading(false) })
  }

  const sorted = [...items].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity
    const bv = b[sortKey] ?? -Infinity
    return sortAsc ? av - bv : bv - av
  })

  const thCls = (key: string) =>
    `cursor-pointer select-none px-2 py-2 text-right text-xs font-medium text-gray-500 hover:text-indigo-600 ${sortKey === key ? 'text-indigo-600' : ''}`
  const sort = (key: string) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(false) }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-gray-800">モメンタム ランキング</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">セクター</label>
            <select
              className="border border-gray-200 rounded px-2 py-1 text-sm"
              value={filters.sector}
              onChange={e => setFilters(f => ({ ...f, sector: e.target.value }))}
            >
              <option value="">全セクター</option>
              {sectors.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">配当スコア下限</label>
            <input type="number" placeholder="例: 70"
              className="border border-gray-200 rounded px-2 py-1 text-sm w-20"
              value={filters.min_div_score}
              onChange={e => setFilters(f => ({ ...f, min_div_score: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">時価総額</label>
            <div className="flex gap-1">
              {(['large_cap', 'mid_cap', 'small_cap'] as const).map(k => (
                <button key={k}
                  onClick={() => setFilters(f => ({ ...f, [k]: !f[k] }))}
                  className={`px-2 py-1 text-xs rounded border transition ${filters[k] ? 'bg-indigo-100 border-indigo-400 text-indigo-700' : 'border-gray-200 text-gray-500'}`}
                >
                  {k === 'large_cap' ? '大型' : k === 'mid_cap' ? '中型' : '小型'}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={load}
            className="px-4 py-1.5 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 transition"
          >
            {loading ? '読込中...' : '検索'}
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-100 bg-gray-50">
            <tr>
              <th className="px-2 py-2 text-left text-xs text-gray-500">#</th>
              <th className="px-2 py-2 text-left text-xs text-gray-500">コード</th>
              <th className="px-2 py-2 text-left text-xs text-gray-500">銘柄名</th>
              <th className="px-2 py-2 text-left text-xs text-gray-500">セクター</th>
              <th className={thCls('momentum_score')} onClick={() => sort('momentum_score')}>Mスコア{sortKey==='momentum_score'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('ret_12m')} onClick={() => sort('ret_12m')}>12M騰落{sortKey==='ret_12m'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('rel_ret_12m')} onClick={() => sort('rel_ret_12m')}>12M相対{sortKey==='rel_ret_12m'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('ret_3m')} onClick={() => sort('ret_3m')}>3M騰落{sortKey==='ret_3m'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('rel_ret_3m')} onClick={() => sort('rel_ret_3m')}>3M相対{sortKey==='rel_ret_3m'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('hi52_ratio')} onClick={() => sort('hi52_ratio')}>高値比{sortKey==='hi52_ratio'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('rev_growth')} onClick={() => sort('rev_growth')}>売上成長{sortKey==='rev_growth'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('eps_growth')} onClick={() => sort('eps_growth')}>EPS成長{sortKey==='eps_growth'?(sortAsc?'↑':'↓'):''}</th>
              <th className={thCls('market_cap')} onClick={() => sort('market_cap')}>時価総額{sortKey==='market_cap'?(sortAsc?'↑':'↓'):''}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={r.code} className="border-b border-gray-50 hover:bg-blue-50/30 transition">
                <td className="px-2 py-2 text-gray-400 text-xs">{i + 1}</td>
                <td className="px-2 py-2">
                  <Link to={`/stock/${r.code}`} className="text-indigo-600 hover:underline font-mono text-xs">{r.code}</Link>
                </td>
                <td className="px-2 py-2 font-medium max-w-[160px] truncate">{r.name}</td>
                <td className="px-2 py-2 text-gray-500 text-xs max-w-[100px] truncate">{r.sector}</td>
                <td className="px-2 py-2 text-right font-bold text-blue-600">{r.momentum_score?.toFixed(1)}</td>
                <td className={`px-2 py-2 text-right text-xs ${r.ret_12m > 0 ? 'text-green-600' : r.ret_12m < 0 ? 'text-red-500' : ''}`}>{fmtRet(r.ret_12m)}</td>
                <td className={`px-2 py-2 text-right text-xs ${r.rel_ret_12m > 0 ? 'text-green-600' : r.rel_ret_12m < 0 ? 'text-red-500' : ''}`}>{fmtRet(r.rel_ret_12m)}</td>
                <td className={`px-2 py-2 text-right text-xs font-semibold ${r.ret_3m > 0 ? 'text-green-600' : 'text-red-500'}`}>{fmtRet(r.ret_3m)}</td>
                <td className={`px-2 py-2 text-right text-xs ${r.rel_ret_3m > 0 ? 'text-green-600' : r.rel_ret_3m < 0 ? 'text-red-500' : ''}`}>{fmtRet(r.rel_ret_3m)}</td>
                <td className="px-2 py-2 text-right text-xs">{r.hi52_ratio != null ? `${r.hi52_ratio}%` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{fmtRet(r.rev_growth)}</td>
                <td className="px-2 py-2 text-right text-xs">{fmtRet(r.eps_growth)}</td>
                <td className="px-2 py-2 text-right text-xs text-gray-600">{fmtCap(r.market_cap)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="px-4 py-2 text-xs text-gray-400">{sorted.length}件</div>
      </div>
    </div>
  )
}
