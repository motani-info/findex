import { Link, useLocation } from 'react-router-dom'

const nav = [
  { path: '/',           label: 'ダッシュボード' },
  { path: '/dividend',   label: '配当ランキング' },
  { path: '/momentum',   label: 'モメンタム' },
  { path: '/search',     label: '銘柄検索' },
  { path: '/indicators', label: '指標ガイド' },
  { path: '/system',     label: 'システム設計' },
  { path: '/commands',   label: 'コマンド' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  return (
    <div className="min-h-screen bg-gray-50 text-gray-800">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6 shadow-sm">
        <span className="font-bold text-lg text-indigo-600 tracking-tight">📈 Findex</span>
        {nav.map(n => (
          <Link
            key={n.path}
            to={n.path}
            className={`text-sm font-medium px-3 py-1 rounded transition
              ${loc.pathname === n.path
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-gray-600 hover:text-indigo-600'}`}
          >
            {n.label}
          </Link>
        ))}
      </nav>
      <main className="max-w-7xl mx-auto px-4 py-6">{children}</main>
    </div>
  )
}
