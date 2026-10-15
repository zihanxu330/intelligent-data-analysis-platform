export default function TradesTable({ trades }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="chart-panel">
        <h3>交易记录</h3>
        <p className="empty-hint">本次回测没有产生任何交易。</p>
      </div>
    );
  }

  return (
    <div className="chart-panel">
      <h3>交易记录（共 {trades.length} 笔）</h3>
      <div className="table-wrap">
        <table className="trades-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>方向</th>
              <th>价格</th>
              <th>数量</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i}>
                <td>{t.date}</td>
                <td>
                  <span className={`badge ${t.action === "buy" ? "badge-buy" : "badge-sell"}`}>
                    {t.action === "buy" ? "买入" : "卖出"}
                  </span>
                </td>
                <td>¥{t.price.toFixed(2)}</td>
                <td>{Math.abs(t.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
