const BASE = "";

async function request(path, options = {}) {
  const res = await fetch(BASE + path, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export const api = {
  getMarkets:      ()             => request("/api/market"),
  getMarket:       (id)           => request(`/api/market/${id}`),
  getTopStocks:    (id, limit=20) => request(`/api/market/${id}/top?limit=${limit}`),
  searchStocks:    (q)            => request(`/api/stock/search?q=${encodeURIComponent(q)}`),
  getStock:        (ticker)       => request(`/api/stock/${encodeURIComponent(ticker)}`),
  getChart:        (ticker, p, i) => request(`/api/stock/${encodeURIComponent(ticker)}/chart?period=${p}&interval=${i}`),
  getStockNews:    (ticker)       => request(`/api/stock/${encodeURIComponent(ticker)}/news`),
  getNews:         (market="all", source="all") => request(`/api/news?market=${market}&source=${source}&limit=30`),
  getCalendar:     ()             => request("/api/calendar"),

  getWatchlist:    ()             => request("/api/watchlist"),
  addWatchlist:    (ticker, market) => request("/api/watchlist", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ ticker, market }),
  }),
  removeWatchlist: (ticker)       => request(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),

  getAlerts:       ()             => request("/api/alert"),
  createAlert:     (body)         => request("/api/alert", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  }),
  deleteAlert:     (id)           => request(`/api/alert/${id}`, { method: "DELETE" }),
};
