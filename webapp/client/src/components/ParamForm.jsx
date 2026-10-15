import { useState } from "react";

const PRESET_SYMBOLS = [
  { code: "600519", name: "贵州茅台" },
  { code: "000001", name: "平安银行" },
  { code: "000858", name: "五粮液" },
  { code: "601318", name: "中国平安" },
  { code: "300750", name: "宁德时代" },
];

export default function ParamForm({ onSubmit, loading }) {
  const [form, setForm] = useState({
    mode: "synthetic",
    symbol: "600519",
    start: "20230101",
    end: "20241231",
    cash: 100000,
    fastPeriod: 10,
    slowPeriod: 30,
  });

  const update = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(form);
  };

  return (
    <form className="param-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label>数据来源</label>
        <div className="mode-toggle">
          <button
            type="button"
            className={form.mode === "synthetic" ? "active" : ""}
            onClick={() => update("mode", "synthetic")}
          >
            合成数据（离线测试）
          </button>
          <button
            type="button"
            className={form.mode === "real" ? "active" : ""}
            onClick={() => update("mode", "real")}
          >
            真实A股数据
          </button>
        </div>
      </div>

      {form.mode === "real" && (
        <>
          <div className="form-row">
            <label>股票代码</label>
            <div className="symbol-row">
              <input
                type="text"
                value={form.symbol}
                onChange={(e) => update("symbol", e.target.value.trim())}
                placeholder="如 600519"
                maxLength={6}
              />
              <select
                onChange={(e) => e.target.value && update("symbol", e.target.value)}
                defaultValue=""
              >
                <option value="" disabled>常用股票</option>
                {PRESET_SYMBOLS.map((s) => (
                  <option key={s.code} value={s.code}>{s.name} ({s.code})</option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-row two-col">
            <div>
              <label>开始日期</label>
              <input
                type="text"
                value={form.start}
                onChange={(e) => update("start", e.target.value.trim())}
                placeholder="YYYYMMDD"
              />
            </div>
            <div>
              <label>结束日期</label>
              <input
                type="text"
                value={form.end}
                onChange={(e) => update("end", e.target.value.trim())}
                placeholder="YYYYMMDD"
              />
            </div>
          </div>
        </>
      )}

      <div className="form-row two-col">
        <div>
          <label>快线周期</label>
          <input
            type="number"
            min={2}
            value={form.fastPeriod}
            onChange={(e) => update("fastPeriod", Number(e.target.value))}
          />
        </div>
        <div>
          <label>慢线周期</label>
          <input
            type="number"
            min={3}
            value={form.slowPeriod}
            onChange={(e) => update("slowPeriod", Number(e.target.value))}
          />
        </div>
      </div>

      <div className="form-row">
        <label>初始资金</label>
        <input
          type="number"
          min={1000}
          step={1000}
          value={form.cash}
          onChange={(e) => update("cash", Number(e.target.value))}
        />
      </div>

      <button type="submit" className="run-btn" disabled={loading}>
        {loading ? "回测运行中…" : "运行回测"}
      </button>
    </form>
  );
}
