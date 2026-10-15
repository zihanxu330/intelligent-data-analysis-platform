const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:3001";

export async function runBacktest(params) {
  const res = await fetch(`${API_BASE}/api/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `请求失败 (HTTP ${res.status})`);
  }
  return res.json();
}
