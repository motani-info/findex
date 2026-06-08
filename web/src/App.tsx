import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import DividendRank from './pages/DividendRank'
import MomentumRank from './pages/MomentumRank'
import Search from './pages/Search'
import StockDetail from './pages/StockDetail'
import Indicators from './pages/Indicators'
import SystemDesign from './pages/SystemDesign'
import Commands from './pages/Commands'

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/"            element={<Dashboard />} />
          <Route path="/dividend"    element={<DividendRank />} />
          <Route path="/momentum"    element={<MomentumRank />} />
          <Route path="/search"      element={<Search />} />
          <Route path="/stock/:code" element={<StockDetail />} />
          <Route path="/indicators"  element={<Indicators />} />
          <Route path="/system"      element={<SystemDesign />} />
          <Route path="/commands"    element={<Commands />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
