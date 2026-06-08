import { useState } from 'react'
import { Link } from 'react-router-dom'
import { searchStocks } from '../api'

const fmtCap = (v?: number) => {
  if (!v) return '-'
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}兆`
  if (v >= 1e8)  return `${(v / 1e8).toFixed(0)}億`
  return `${v}`
}

export default function Search() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const search = async (val: string) => {
    setQ(val)
    if (val.length < 1) { setResults([]); return }
    setLoading(true)
    const data = await searchStocks(val)
    setResults(data.items)
    setLoading(false)
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-800">銘柄検索</h1>

      <div className="relative">
        <input
          type="text"
          placeholder="銘柄コードまたは銘柄名で検索（例: 8316 / 三井）"
          className="w-full border border-gray-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
          value={q}
          onChange={e => search(e.target.value)}
          autoFocus
        />
        {loading && <span className="absolute right-4 top-3 text-gray-400 text-sm">検索中...</span>}
      </div>

      {results.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs text-gray-500">コード</th>
                <th className="px-4 py-2 text-left text-xs text-gray-500">銘柄名</th>
                <th className="px-4 py-2 text-left text-xs text-gray-500">セクター</th>
                <th className="px-4 py-2 text-left text-xs text-gray-500">市場</th>
                <th className="px-4 py-2 text-right text-xs text-gray-500">スコア</th>
                <th className="px-4 py-2 text-right text-xs text-gray-500">利回り</th>
                <th className="px-4 py-2 text-right text-xs text-gray-500">時価総額</th>
              </tr>
            </thead>
            <tbody>
              {results.map(r => (
                <tr key={r.code} className="border-b border-gray-50 hover:bg-indigo-50/40 transition">
                  <td className="px-4 py-2">
                    <Link to={`/stock/${r.code}`} className="text-indigo-600 hover:underline font-mono">{r.code}</Link>
                  </td>
                  <td className="px-4 py-2 font-medium">{r.name}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.sector}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.market}</td>
                  <td className="px-4 py-2 text-right font-semibold text-indigo-600">{r.score?.toFixed(1)}</td>
                  <td className="px-4 py-2 text-right text-green-600">{r.div_yield ? `${r.div_yield}%` : '-'}</td>
                  <td className="px-4 py-2 text-right text-xs text-gray-600">{fmtCap(r.market_cap)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {q.length > 0 && results.length === 0 && !loading && (
        <p className="text-gray-400 text-sm">「{q}」に一致する銘柄が見つかりませんでした。</p>
      )}
    </div>
  )
}
