// server.js
// Node.js API后端：接收前端的回测请求参数，调用Python的 main.py 跑真正的回测逻辑，
// 读取Python写出的JSON结果文件后转发给前端。Node这一层不做任何金融计算，
// 只负责参数校验、进程调度、结果透传 —— 计算全部在Python/backtrader里完成。

import express from "express";
import cors from "cors";
import { spawn } from "child_process";
import { randomUUID } from "crypto";
import { readFile, unlink, mkdir } from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// quant_ai 项目根目录（webapp/server 的上两级）
const QUANT_ROOT = path.resolve(__dirname, "..", "..");
const RUNS_DIR = path.join(QUANT_ROOT, "output", "api_runs");

// Windows下常见是 "python"，Mac/Linux常见是 "python3"。
// 可以通过环境变量 PYTHON_BIN 覆盖，比如 PYTHON_BIN=py（Windows启动器）。
const PYTHON_BIN = process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3");

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3001;

function runPythonBacktest(params) {
  return new Promise(async (resolve, reject) => {
    await mkdir(RUNS_DIR, { recursive: true });
    const runId = randomUUID();
    const jsonOutPath = path.join(RUNS_DIR, `${runId}.json`);

    const args = [
      "main.py",
      "--mode", params.mode,
      "--symbol", params.symbol,
      "--start", params.start,
      "--end", params.end,
      "--cash", String(params.cash),
      "--fast-period", String(params.fastPeriod),
      "--slow-period", String(params.slowPeriod),
      "--json-out", jsonOutPath,
      "--no-plot",
    ];

    const proc = spawn(PYTHON_BIN, args, { cwd: QUANT_ROOT });

    let stderr = "";
    let stdout = "";
    proc.stdout.on("data", (d) => { stdout += d.toString(); });
    proc.stderr.on("data", (d) => { stderr += d.toString(); });

    proc.on("error", (err) => {
      // 通常是找不到python可执行文件
      reject(new Error(
        `无法启动Python进程（尝试命令: ${PYTHON_BIN}）。请确认已安装Python并加入PATH，` +
        `或设置环境变量 PYTHON_BIN 指定正确命令。原始错误: ${err.message}`
      ));
    });

    proc.on("close", async (code) => {
      if (code !== 0) {
        reject(new Error(`Python回测脚本运行失败 (exit code ${code}):\n${stderr || stdout}`));
        return;
      }
      try {
        const raw = await readFile(jsonOutPath, "utf-8");
        const result = JSON.parse(raw);
        resolve(result);
      } catch (e) {
        reject(new Error(`读取回测结果JSON失败: ${e.message}\nPython输出: ${stdout}\n${stderr}`));
      } finally {
        // 清理临时结果文件，避免output/api_runs无限堆积
        unlink(jsonOutPath).catch(() => {});
      }
    });
  });
}

app.get("/api/health", (req, res) => {
  res.json({ status: "ok" });
});

app.post("/api/backtest", async (req, res) => {
  const {
    mode = "synthetic",
    symbol = "600519",
    start = "20230101",
    end = "20241231",
    cash = 100000,
    fastPeriod = 10,
    slowPeriod = 30,
  } = req.body || {};

  if (!["synthetic", "real"].includes(mode)) {
    return res.status(400).json({ error: "mode 必须是 'synthetic' 或 'real'" });
  }
  const cashValue = Number(cash);
  const fastValue = Number(fastPeriod);
  const slowValue = Number(slowPeriod);
  const isDate = (value) => {
    if (typeof value !== "string" || !/^\d{8}$/.test(value)) return false;
    const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
    const parsed = new Date(`${iso}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso;
  };

  if (!Number.isFinite(cashValue) || cashValue <= 0) {
    return res.status(400).json({ error: "cash 必须是大于0的有限数值" });
  }
  if (!Number.isInteger(fastValue) || !Number.isInteger(slowValue) || fastValue < 1 || slowValue < 2) {
    return res.status(400).json({ error: "均线周期必须是正整数，且慢线周期至少为2" });
  }
  if (fastValue >= slowValue) {
    return res.status(400).json({ error: "快线周期(fastPeriod)必须小于慢线周期(slowPeriod)" });
  }
  if (!isDate(start) || !isDate(end) || start > end) {
    return res.status(400).json({ error: "start/end 必须是有效的 YYYYMMDD 日期，且 start 不晚于 end" });
  }
  if (mode === "real" && (typeof symbol !== "string" || !/^\d{6}$/.test(symbol))) {
    return res.status(400).json({ error: "真实行情模式的 symbol 必须是6位股票代码" });
  }

  try {
    const result = await runPythonBacktest({
      mode, symbol, start, end, cash: cashValue,
      fastPeriod: fastValue, slowPeriod: slowValue,
    });
    res.json(result);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// 生产部署：单服务托管前端静态产物（client/dist 由 npm run build 生成）
const CLIENT_DIST = path.resolve(__dirname, "..", "client", "dist");
app.use(express.static(CLIENT_DIST));
// SPA fallback：非API路由回退到前端入口
app.get("*", (req, res, next) => {
  if (req.path.startsWith("/api/")) return next();
  res.sendFile(path.join(CLIENT_DIST, "index.html"));
});

app.listen(PORT, () => {
  console.log(`量化回测API服务已启动: http://localhost:${PORT}`);
  console.log(`Python命令: ${PYTHON_BIN}  (可用环境变量 PYTHON_BIN 覆盖)`);
  console.log(`Python项目根目录: ${QUANT_ROOT}`);
});
