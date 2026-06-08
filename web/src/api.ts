import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getDividendRank = (params: Record<string, unknown>) =>
  api.get('/dividend/rank', { params }).then(r => r.data)

export const getDividendCheck = (code: string) =>
  api.get(`/dividend/check/${code}`).then(r => r.data)

export const getMomentumRank = (params: Record<string, unknown>) =>
  api.get('/momentum/rank', { params }).then(r => r.data)

export const getMomentumCheck = (code: string) =>
  api.get(`/momentum/check/${code}`).then(r => r.data)

export const searchStocks = (q: string) =>
  api.get('/stock/search', { params: { q } }).then(r => r.data)

export const getPriceHistory = (code: string) =>
  api.get(`/stock/price-history/${code}`).then(r => r.data)

export const getDividendHistory = (code: string) =>
  api.get(`/stock/dividend-history/${code}`).then(r => r.data)

export const getStats = () =>
  api.get('/update/stats').then(r => r.data)

export const getSectors = () =>
  api.get('/stock/sectors').then(r => r.data)

export const getMarkets = () =>
  api.get('/stock/markets').then(r => r.data)
