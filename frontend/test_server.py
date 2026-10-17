# -*- coding: utf-8 -*-
"""验证 webapp 单服务（前端 + API）可访问性。"""
import json
import urllib.request

BASE = "http://localhost:3001"

lines = []

# 1) 前端页面
r = urllib.request.urlopen(BASE + "/", timeout=10)
html = r.read().decode("utf-8")
lines.append("frontend: %s react-root: %s" % (r.status, 'id="root"' in html))

# 2) health
h = urllib.request.urlopen(BASE + "/api/health", timeout=10)
lines.append("health: %s %s" % (h.status, h.read().decode()))

# 3) 真实回测（快速小样本）
body = json.dumps({"mode": "real", "symbol": "600519",
                   "start": "20240101", "end": "20240630",
                   "cash": 100000, "fastPeriod": 10, "slowPeriod": 30}).encode()
req = urllib.request.Request(BASE + "/api/backtest", data=body,
                             headers={"Content-Type": "application/json"})
b = urllib.request.urlopen(req, timeout=120)
res = json.loads(b.read().decode("utf-8"))
lines.append("backtest metrics: %s" % json.dumps(res.get("metrics"), ensure_ascii=False))
lines.append("candles: %d | equity: %d | trades: %d" % (
    len(res.get("candles", [])), len(res.get("equity_curve", [])), len(res.get("trades", []))))

report = "\n".join(lines)
with open(r"C:\Users\22646\Desktop\项目\quant_ai_updated\quant\frontend\server_test_result.txt",
          "w", encoding="utf-8") as f:
    f.write(report + "\n")
