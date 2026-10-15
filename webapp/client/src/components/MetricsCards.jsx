const METRIC_META = [
  { key: "total_return", label: "总收益率", fmt: (v) => `${(v * 100).toFixed(2)}%`, sign: true },
  { key: "final_value", label: "期末资金", fmt: (v) => `¥${v.toLocaleString()}` },
  { key: "sharpe_ratio", label: "夏普比率", fmt: (v) => (v === null ? "—" : v.toFixed(2)) },
  { key: "max_drawdown_pct", label: "最大回撤", fmt: (v) => `${v.toFixed(2)}%` },
  { key: "total_trades", label: "交易次数", fmt: (v) => v },
  { key: "win_rate", label: "胜率", fmt: (v) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`) },
];

export default function MetricsCards({ metrics }) {
  if (!metrics) return null;

  return (
    <div className="metrics-grid">
      {METRIC_META.map(({ key, label, fmt, sign }) => {
        const value = metrics[key];
        const numeric = typeof value === "number" ? value : null;
        const isPositive = sign && numeric !== null ? numeric >= 0 : null;
        return (
          <div className="metric-card" key={key}>
            <div className="metric-label">{label}</div>
            <div
              className={
                "metric-value" +
                (isPositive === true ? " positive" : isPositive === false ? " negative" : "")
              }
            >
              {value === null || value === undefined ? "—" : fmt(value)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
