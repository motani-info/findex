import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getDividendCheck, getMomentumCheck, getPriceHistory, getDividendHistory } from '../api'
import ScoreBar from '../components/ScoreBar'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, BarElement, Title, Tooltip, Legend,
} from 'chart.js'
import { Line, Bar } from 'react-chartjs-2'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Title, Tooltip, Legend)

const MOM_LABELS: Record<string, string> = {
  rel_ret_3m:       '相対リターン(3ヶ月)',
  rel_ret_12m:      '相対リターン(12ヶ月)',
  hi52_ratio:       '52週高値比',
  rev_growth:       '売上成長率',
  eps_growth:       'EPS成長率',
  roe:              'ROE',
  operating_margin: '営業利益率',
  vol_ratio:        '出来高増加率',
}

const SCORE_LABELS: Record<string, string> = {
  consecutive_no_cut_years:           '連続非減配年数',
  consecutive_dividend_growth_years:  '連続増配年数',
  dividend_reliability:               '配当信頼性',
  dividend_growth_10y_cagr:           '10年配当CAGR',
  payout_ratio:                       '配当性向',
  fcf_payout_coverage:                'FCF配当カバレッジ',
  eps_growth_5y:                      'EPS成長率(5年)',
  revenue_growth_5y_cagr:             '売上成長率(5年)',
  equity_ratio:                       '自己資本比率',
  roe:                                'ROE',
  operating_margin:                   '営業利益率',
  roic_minus_wacc:                    'ROIC−WACC',
  div_yield:                          '配当利回り',
  net_cash_per:                       'ネットキャッシュPER',
  retained_earnings_div_ratio:        '利益剰余金配当倍率',
  mix_coefficient:                    'PER×PBR',
}

const fmtCap = (v?: number) => {
  if (!v) return '-'
  if (v >= 1e12) return `${(v / 1e12).toFixed(1)}兆円`
  if (v >= 1e8)  return `${(v / 1e8).toFixed(0)}億円`
  return `${v}`
}


export default function StockDetail() {
  const { code } = useParams<{ code: string }>()
  const [div, setDiv] = useState<any>(null)
  const [mom, setMom] = useState<any>(null)
  const [priceHist, setPriceHist] = useState<any[]>([])
  const [divHist, setDivHist] = useState<any[]>([])
  const [tab, setTab] = useState<'dividend' | 'momentum'>('dividend')

  useEffect(() => {
    if (!code) return
    getDividendCheck(code).then(setDiv)
    getMomentumCheck(code).then(setMom)
    getPriceHistory(code).then(d => setPriceHist(d.history))
    getDividendHistory(code).then(d => setDivHist(d.history))
  }, [code])

  if (!div) return <div className="p-8 text-gray-400">読み込み中...</div>
  if (div.error) return <div className="p-8 text-red-500">銘柄 {code} が見つかりません</div>

  const raw = div.raw || {}

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm text-gray-400 mb-1">
            <Link to="/search" className="hover:underline text-indigo-500">検索</Link> › {code}
          </div>
          <h1 className="text-2xl font-bold text-gray-800">{div.name}</h1>
          <div className="flex gap-2 mt-1">
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{div.sector}</span>
            <span className="text-xs text-gray-400">時価総額 {fmtCap(raw.market_cap)}</span>
            <span className="text-xs text-gray-400">更新: {div.updated_at}</span>
          </div>
        </div>
        <div className="flex gap-4 text-center">
          <div className="bg-indigo-50 rounded-xl px-5 py-3">
            <div className="text-3xl font-bold text-indigo-600">{div.total_score?.toFixed(1)}</div>
            <div className="text-xs text-gray-500 mt-0.5">配当スコア</div>
          </div>
          {mom && !mom.error && (
            <div className="bg-blue-50 rounded-xl px-5 py-3">
              <div className="text-3xl font-bold text-blue-600">{mom.momentum_score?.toFixed(1)}</div>
              <div className="text-xs text-gray-500 mt-0.5">モメンタム</div>
            </div>
          )}
        </div>
      </div>

      {/* Tab */}
      <div className="flex gap-2 border-b border-gray-200">
        {(['dividend', 'momentum'] as const).map(t => (
          <button key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${
              tab === t ? 'border-indigo-500 text-indigo-700' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'dividend' ? '配当スコア詳細' : 'モメンタム詳細'}
          </button>
        ))}
      </div>

      {tab === 'dividend' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Score breakdown */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h2 className="font-semibold text-gray-700 mb-3 text-sm">スコア内訳</h2>
            <div className="space-y-1.5">
              {Object.entries(div.breakdown || {})
                .sort(([, a]: any, [, b]: any) => b - a)
                .map(([key, val]: [string, any]) => (
                  <ScoreBar key={key} label={SCORE_LABELS[key] ?? key.replace(/_/g, ' ')} value={val} max={10} />
                ))}
            </div>
          </div>

          {/* Key metrics */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h2 className="font-semibold text-gray-700 mb-3 text-sm">主要指標</h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                ['配当利回り', raw.div_yield ? `${(raw.div_yield * 100).toFixed(2)}%` : '-'],
                ['連続非減配', raw.consecutive_no_cut_years != null ? `${raw.consecutive_no_cut_years}年` : '-'],
                ['連続増配', raw.consecutive_dividend_growth_years != null ? `${raw.consecutive_dividend_growth_years}年` : '-'],
                ['5年配当CAGR', raw.dividend_growth_5y_cagr ? `${(raw.dividend_growth_5y_cagr * 100).toFixed(1)}%` : '-'],
                ['PER', raw.per ? `${raw.per.toFixed(1)}倍` : '-'],
                ['PBR', raw.pbr ? `${raw.pbr.toFixed(2)}倍` : '-'],
                ['ROE', raw.roe ? `${(raw.roe * 100).toFixed(1)}%` : '-'],
                ['自己資本比率', raw.equity_ratio ? `${(raw.equity_ratio * 100).toFixed(1)}%` : '-'],
                ['配当性向', raw.payout_ratio ? `${(raw.payout_ratio * 100).toFixed(1)}%` : '-'],
                ['20年減配回数', raw.dividend_cut_count_20y != null ? `${raw.dividend_cut_count_20y}回` : '-'],
              ].map(([label, value]) => (
                <div key={label} className="bg-gray-50 rounded-lg p-2">
                  <div className="text-xs text-gray-400">{label}</div>
                  <div className="font-semibold text-gray-800 text-sm">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'momentum' && mom && !mom.error && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h2 className="font-semibold text-gray-700 mb-3 text-sm">モメンタム指標</h2>
            <div className="space-y-2">
              {Object.entries(mom.breakdown || {}).map(([key, val]: [string, any]) => (
                <ScoreBar key={key} label={MOM_LABELS[key] ?? key.replace(/_/g, ' ')} value={val} max={10} />
              ))}
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h2 className="font-semibold text-gray-700 mb-3 text-sm">実値</h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                ['12Mリターン', mom.fields?.ret_12m != null ? `${mom.fields.ret_12m > 0 ? '+' : ''}${mom.fields.ret_12m}%` : '-'],
                ['3Mリターン',  mom.fields?.ret_3m  != null ? `${mom.fields.ret_3m > 0 ? '+' : ''}${mom.fields.ret_3m}%` : '-'],
                ['52週高値比率', mom.fields?.hi52_ratio != null ? `${mom.fields.hi52_ratio}%` : '-'],
                ['売上成長率',  mom.fields?.rev_growth != null ? `${mom.fields.rev_growth > 0 ? '+' : ''}${mom.fields.rev_growth}%` : '-'],
                ['EPS成長率',   mom.fields?.eps_growth != null ? `${mom.fields.eps_growth > 0 ? '+' : ''}${mom.fields.eps_growth}%` : '-'],
              ].map(([label, value]) => (
                <div key={label} className="bg-gray-50 rounded-lg p-2">
                  <div className="text-xs text-gray-400">{label}</div>
                  <div className="font-semibold text-gray-800 text-sm">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Price Chart */}
      {priceHist.length > 1 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h2 className="font-semibold text-gray-700 mb-3 text-sm">株価推移（price_history）</h2>
          <Line
            data={{
              labels: priceHist.map(h => h.date),
              datasets: [{
                label: '終値',
                data: priceHist.map(h => h.close),
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99,102,241,0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
              }],
            }}
            options={{ responsive: true, plugins: { legend: { display: false } } }}
          />
        </div>
      )}

      {/* Dividend History Chart */}
      {divHist.length > 1 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h2 className="font-semibold text-gray-700 mb-3 text-sm">配当履歴</h2>
          <Bar
            data={{
              labels: divHist.map(h => h.date),
              datasets: [{
                label: '配当額（円）',
                data: divHist.map(h => h.amount),
                backgroundColor: 'rgba(34,197,94,0.6)',
              }],
            }}
            options={{ responsive: true, plugins: { legend: { display: false } } }}
          />
        </div>
      )}
    </div>
  )
}
