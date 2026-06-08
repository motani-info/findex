import { useEffect, useState } from 'react'
import axios from 'axios'

type Indicator = {
  label: string
  description: string
  formula: string
  good: string
  warning: string
  unit: string
  weight: number
  direction: 'high' | 'low'
  threshold: number | null
  upper_cap: number | null
  penalty_cap: number | null
  applies_to?: string[]
  status: 'active' | 'pending' | 'todo'
  note?: string | null
}

type ScoringData = {
  dividend: { title: string; description: string; indicators: Indicator[] }
  momentum: { title: string; description: string; indicators: Indicator[] }
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  pending: { label: 'データ蓄積待ち', cls: 'bg-yellow-50 text-yellow-700 border-yellow-200' },
  todo:    { label: '未実装',         cls: 'bg-gray-100  text-gray-400  border-gray-300'   },
}

function WeightDots({ weight, max = 2.5 }: { weight: number; max?: number }) {
  const filled = Math.round((weight / max) * 5)
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className={`w-2 h-2 rounded-full ${i < filled ? 'bg-indigo-400' : 'bg-gray-200'}`} />
      ))}
    </div>
  )
}

function IndicatorRow({ index, ind, accentColor }: {
  index: number
  ind: Indicator
  accentColor: string
}) {
  const [open, setOpen] = useState(false)
  const dimmed = ind.status !== 'active'
  const statusInfo = ind.status !== 'active' ? STATUS_BADGE[ind.status] : null

  return (
    <div className={`border-b border-gray-100 last:border-0 ${dimmed ? 'opacity-50' : ''}`}>
      {/* サマリー行（クリックで展開） */}
      <button
        className="w-full text-left flex items-start gap-3 py-3 hover:bg-gray-50 transition px-0"
        onClick={() => !dimmed && setOpen(o => !o)}
      >
        <span className="shrink-0 w-5 text-right text-xs text-gray-300 font-mono pt-0.5">{index}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`font-medium text-sm ${dimmed ? 'text-gray-400' : 'text-gray-800'}`}>
              {ind.label}
            </span>
            {ind.unit && <span className="text-xs text-gray-400">（{ind.unit}）</span>}
            {statusInfo && (
              <span className={`text-xs border px-1.5 py-0.5 rounded ${statusInfo.cls}`}>
                {statusInfo.label}
              </span>
            )}
            {ind.note && !statusInfo && (
              <span className="text-xs bg-indigo-50 text-indigo-500 border border-indigo-100 px-1.5 py-0.5 rounded">
                {ind.note}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{ind.description}</p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <div className="text-right">
            <WeightDots weight={ind.weight} />
            <span className="text-xs text-gray-400 font-mono">{ind.weight.toFixed(1)}</span>
          </div>
          {!dimmed && (
            <span className="text-gray-300 text-xs">{open ? '▲' : '▼'}</span>
          )}
        </div>
      </button>

      {/* 展開詳細 */}
      {open && (
        <div className={`mx-8 mb-3 rounded-xl border p-4 space-y-3 text-sm ${accentColor}`}>
          <p className="text-gray-700">{ind.description}</p>

          {ind.formula && (
            <div>
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">計算式</div>
              <code className="block bg-white border border-gray-200 rounded px-3 py-2 text-gray-700 text-xs">
                {ind.formula}
              </code>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            {ind.good && (
              <div className="bg-green-50 rounded-lg p-2">
                <div className="text-xs text-green-600 font-semibold mb-0.5">✅ 良い水準</div>
                <div className="text-xs text-green-800">{ind.good}</div>
              </div>
            )}
            {ind.warning && (
              <div className="bg-orange-50 rounded-lg p-2">
                <div className="text-xs text-orange-600 font-semibold mb-0.5">⚠️ 注意</div>
                <div className="text-xs text-orange-800">{ind.warning}</div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2 text-xs">
            {ind.threshold != null && (
              <span className="bg-white border border-gray-200 rounded px-2 py-1 text-gray-600">
                満点閾値: {ind.direction === 'high' ? '≥' : '≤'} {ind.threshold}
                {ind.unit ? ` ${ind.unit}` : ''}
              </span>
            )}
            {ind.upper_cap != null && (
              <span className="bg-orange-50 border border-orange-200 rounded px-2 py-1 text-orange-600">
                upper_cap: {ind.upper_cap} 超で0点
              </span>
            )}
            {ind.penalty_cap != null && (
              <span className="bg-red-50 border border-red-200 rounded px-2 py-1 text-red-600">
                penalty_cap: {ind.penalty_cap} 以上で0点
              </span>
            )}
            {(ind.applies_to ?? []).length > 0 && (
              <span className="bg-blue-50 border border-blue-200 rounded px-2 py-1 text-blue-600">
                {(ind.applies_to ?? []).join(' / ')} のみ適用
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Indicators() {
  const [data, setData] = useState<ScoringData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('/api/rules/scoring').then(r => {
      setData(r.data)
      setLoading(false)
    })
  }, [])

  if (loading) return <div className="p-8 text-gray-400">読み込み中...</div>
  if (!data) return null

  const divActive   = data.dividend.indicators.filter(i => (i.applies_to ?? []).length === 0)
  const divCond     = data.dividend.indicators.filter(i => (i.applies_to ?? []).length > 0)
  const momActive   = data.momentum.indicators.filter(i => i.status === 'active')
  const momInactive = data.momentum.indicators.filter(i => i.status !== 'active')

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-800">スコアリング指標</h1>
        <p className="text-sm text-gray-500 mt-1">
          各スコアがどの指標をもとに計算されているか。行をクリックで定義・計算式を表示。
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* 配当スコア */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="bg-green-50 px-5 py-4 border-b border-green-100">
            <div className="flex items-center gap-2">
              <span className="text-2xl">💰</span>
              <div>
                <h2 className="font-bold text-gray-800">{data.dividend.title}</h2>
                <p className="text-xs text-gray-500 mt-0.5">{data.dividend.description}</p>
              </div>
            </div>
          </div>

          <div className="px-5">
            {divActive.map((ind, i) => (
              <IndicatorRow key={ind.label} index={i + 1} ind={ind} accentColor="bg-green-50 border-green-100" />
            ))}
          </div>

          {divCond.length > 0 && (
            <>
              <div className="px-5 py-2 bg-gray-50 border-t border-gray-100">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  大型株・金融株のみ（動的入れ替え）
                </span>
              </div>
              <div className="px-5">
                {divCond.map((ind, i) => (
                  <IndicatorRow key={ind.label} index={divActive.length + i + 1} ind={ind} accentColor="bg-green-50 border-green-100" />
                ))}
              </div>
            </>
          )}

          <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
            <p className="text-xs text-gray-400">
              {divActive.length} 指標（全銘柄）+ {divCond.length} 指標（条件付き）→ 100点換算
            </p>
          </div>
        </div>

        {/* モメンタムスコア */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="bg-blue-50 px-5 py-4 border-b border-blue-100">
            <div className="flex items-center gap-2">
              <span className="text-2xl">🚀</span>
              <div>
                <h2 className="font-bold text-gray-800">{data.momentum.title}</h2>
                <p className="text-xs text-gray-500 mt-0.5">{data.momentum.description}</p>
              </div>
            </div>
          </div>

          <div className="px-5">
            {momActive.map((ind, i) => (
              <IndicatorRow key={ind.label} index={i + 1} ind={ind} accentColor="bg-blue-50 border-blue-100" />
            ))}
          </div>

          {momInactive.length > 0 && (
            <>
              <div className="px-5 py-2 bg-gray-50 border-t border-gray-100">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  追加予定
                </span>
              </div>
              <div className="px-5">
                {momInactive.map((ind, i) => (
                  <IndicatorRow key={ind.label} index={momActive.length + i + 1} ind={ind} accentColor="bg-blue-50 border-blue-100" />
                ))}
              </div>
            </>
          )}

          <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
            <p className="text-xs text-gray-400">
              実装済み {momActive.length} 指標 → 100点換算（残り {momInactive.length} 指標は追加予定）
            </p>
          </div>
        </div>

      </div>

      <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-4 text-sm text-indigo-800">
        <span className="font-semibold">📊 スコアの計算方法: </span>
        各指標を0〜10点で評価し、重み（●の数）を掛けて合算。最終スコアは100点満点に換算されます。
      </div>
    </div>
  )
}
