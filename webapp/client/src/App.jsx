import { useState } from "react";
import ParamForm from "./components/ParamForm";
import MetricsCards from "./components/MetricsCards";
import EquityCurveChart from "./components/EquityCurveChart";
import CandlestickChart from "./components/CandlestickChart";
import TradesTable from "./components/TradesTable";
import { runBacktest } from "./api";

export default function App() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (params) => {
    setLoading(true);
    setError(null);
    try {
      const data = await runBacktest(params);
      setResult(data);
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>量化回测面板</h1>
        <p className="subtitle">合成行情 / A股数据 · 多因子规则策略 · Python + backtrader</p>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <ParamForm onSubmit={handleSubmit} loading={loading} />
          <p className="disclaimer">
            回测结果基于历史数据，不代表未来表现，仅供策略验证参考，不构成投资建议。
          </p>
        </aside>

        <main className="main-content">
          {error && <div className="error-banner">运行出错：{error}</div>}

          {!result && !error && !loading && (
            <div className="empty-state">
              在左侧设置参数后点击"运行回测"，结果会显示在这里。
            </div>
          )}

          {loading && <div className="empty-state">回测运行中，请稍候…</div>}

          {result && (
            <>
              <MetricsCards metrics={result.metrics} />
              <CandlestickChart candles={result.candles} trades={result.trades} />
              <EquityCurveChart data={result.equity_curve} />
              <TradesTable trades={result.trades} />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
