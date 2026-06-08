import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDividendRank, getSectors } from '../api'

const fmtCap = (v?: number) => {
  if (!v) return '-'
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}兆`
  if (v >= 1e8)  return `${(v / 1e8).toFixed(0)}億`
  return `${v}`
}

export default function DividendRank() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [sectors, setSectors] = useState<string[]>([])
  const [filters, setFilters] = useState({
    top: 50, sector: '', min_yield: '', large_cap: false,
    mid_cap: false, small_cap: false, max_per: '', max_pbr: '',
  })
  const [sortKey, setSortKey] = useState('score')
  const [sortAsc, setSortAsc] = useState(false)

  useEffect(() => {
    getSectors().then(d => setSectors(d.sectors))
    load()
  }, [])

  const load = () => {
    setLoading(true)
    const params: Record<string, unknown> = { top: filters.top }
    if (filters.sector)    params.sector    = filters.sector
    if (filters.min_yield) params.min_yield = parseFloat(filters.min_yield) / 100
    if (filters.large_cap) params.large_cap = true
    if (filters.mid_cap)   params.mid_cap   = true
    if (filters.small_cap) params.small_cap = true
    if (filters.max_per)   params.max_per   = parseFloat(filters.max_per)
    if (filters.max_pbr)   params.max_pbr   = parseFloat(filters.max_pbr)
    getDividendRank(params).then(d => { setItems(d.items); setLoading(false) })
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
      <h1 className="text-2xl font-bold text-gray-800">配当スコア ランキング</h1>

      {/* Filters */}
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
            <label className="text-xs text-gray-500 block mb-1">最低利回り(%)</label>
            <input type="number" step="0.1" placeholder="例: 3.0"
              className="border border-gray-200 rounded px-2 py-1 text-sm w-24"
              value={filters.min_yield}
              onChange={e => setFilters(f => ({ ...f, min_yield: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">PER上限</label>
            <input type="number" placeholder="例: 20"
              className="border border-gray-200 rounded px-2 py-1 text-sm w-20"
              value={filters.max_per}
              onChange={e => setFilters(f => ({ ...f, max_per: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">PBR上限</label>
            <input type="number" step="0.1" placeholder="例: 2.0"
              className="border border-gray-200 rounded px-2 py-1 text-sm w-20"
              value={filters.max_pbr}
              onChange={e => setFilters(f => ({ ...f, max_pbr: e.target.value }))} />
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

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-100 bg-gray-50">
            <tr>
              <th className="px-2 py-2 text-left text-xs text-gray-500">#</th>
              <th className="px-2 py-2 text-left text-xs text-gray-500">コード</th>
              <th className="px-2 py-2 text-left text-xs text-gray-500">銘柄名</th>
              <th className="px-2 py-2 text-left text-xs text-gray-500">セクター</th>
              <th className={thCls('score')} onClick={() => sort('score')}>スコア{sortKey==='score' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('div_yield')} onClick={() => sort('div_yield')}>利回り{sortKey==='div_yield' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('market_cap')} onClick={() => sort('market_cap')}>時価総額{sortKey==='market_cap' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('per')} onClick={() => sort('per')}>PER{sortKey==='per' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('pbr')} onClick={() => sort('pbr')}>PBR{sortKey==='pbr' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('roe')} onClick={() => sort('roe')}>ROE{sortKey==='roe' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('op_margin')} onClick={() => sort('op_margin')}>営業利益率{sortKey==='op_margin' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('equity_ratio')} onClick={() => sort('equity_ratio')}>自己資本比{sortKey==='equity_ratio' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('payout_ratio')} onClick={() => sort('payout_ratio')}>配当性向{sortKey==='payout_ratio' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('no_cut')} onClick={() => sort('no_cut')}>非減配{sortKey==='no_cut' ? (sortAsc?'↑':'↓') : ''}</th>
              <th className={thCls('div_growth')} onClick={() => sort('div_growth')}>連続増配{sortKey==='div_growth' ? (sortAsc?'↑':'↓') : ''}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={r.code} className="border-b border-gray-50 hover:bg-indigo-50/30 transition">
                <td className="px-2 py-2 text-gray-400 text-xs">{i + 1}</td>
                <td className="px-2 py-2">
                  <Link to={`/stock/${r.code}`} className="text-indigo-600 hover:underline font-mono text-xs">{r.code}</Link>
                </td>
                <td className="px-2 py-2 font-medium max-w-[160px] truncate">{r.name}</td>
                <td className="px-2 py-2 text-gray-500 text-xs max-w-[100px] truncate">{r.sector}</td>
                <td className="px-2 py-2 text-right">
                  <span className={`font-bold ${r.score >= 80 ? 'text-green-600' : r.score >= 70 ? 'text-indigo-600' : 'text-gray-700'}`}>
                    {r.score?.toFixed(1)}
                  </span>
                </td>
                <td className="px-2 py-2 text-right text-green-600">{r.div_yield ? `${r.div_yield}%` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs text-gray-600">{fmtCap(r.market_cap)}</td>
                <td className="px-2 py-2 text-right text-xs">{r.per?.toFixed(1) ?? '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.pbr?.toFixed(2) ?? '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.roe ? `${r.roe}%` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.op_margin != null ? `${r.op_margin}%` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.equity_ratio != null ? `${r.equity_ratio}%` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.payout_ratio != null ? `${r.payout_ratio}%` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.no_cut != null ? `${r.no_cut}年` : '-'}</td>
                <td className="px-2 py-2 text-right text-xs">{r.div_growth != null ? `${r.div_growth}年` : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="px-4 py-2 text-xs text-gray-400">{sorted.length}件</div>
      </div>
    </div>
  )
}
