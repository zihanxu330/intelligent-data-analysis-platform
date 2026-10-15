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
  if (Number(fastPeriod) >= Number(slowPeriod)) {
    return res.status(400).json({ error: "快线周期(fastPeriod)必须小于慢线周期(slowPeriod)" });
  }

  try {
    const result = await runPythonBacktest({
      mode, symbol, start, end, cash, fastPeriod, slowPeriod,
    });
    res.json(result);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`量化回测API服务已启动: http://localhost:${PORT}`);
  console.log(`Python命令: ${PYTHON_BIN}  (可用环境变量 PYTHON_BIN 覆盖)`);
  console.log(`Python项目根目录: ${QUANT_ROOT}`);
});
