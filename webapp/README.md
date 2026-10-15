# quant_ai 可视化前端（Node.js + React）

在 `quant_ai` 的Python回测系统基础上，加了一层Web界面：

```
浏览器(React) → HTTP → Node.js/Express API → 子进程调用 python main.py → 读取JSON结果 → 返回给前端
```

Python这边完全不用改动使用方式，Node只是调度者，不做任何计算。

## 目录结构

```
webapp/
├── server/          # Node.js/Express API
│   ├── server.js
│   └── package.json
└── client/           # React前端（Vite + recharts + lightweight-charts）
    ├── src/
    │   ├── App.jsx
    │   ├── api.js
    │   └── components/
    │       ├── ParamForm.jsx        # 参数表单：股票、日期、均线周期
    │       ├── MetricsCards.jsx     # 绩效指标卡片
    │       ├── CandlestickChart.jsx # K线图 + 均线叠加 + 买卖点标记
    │       ├── EquityCurveChart.jsx # 资金曲线
    │       └── TradesTable.jsx      # 逐笔交易记录
    └── package.json
```

## 安装

需要先按 `quant_ai/README.md` 装好Python依赖（`pip install -r requirements.txt`），
Node这边额外装两份依赖：

```bash
cd webapp/server
npm install

cd ../client
npm install
```

## 启动（需要开两个终端）

**终端1 —— 启动API服务：**
```bash
cd webapp/server
npm start
```
默认监听 `http://localhost:3001`。

Windows下如果Python命令是 `py` 而不是 `python`/`python3`，启动前设置一下环境变量：
```cmd
set PYTHON_BIN=py
npm start
```

**终端2 —— 启动前端：**
```bash
cd webapp/client
npm run dev
```
默认在 `http://localhost:5173` 打开，浏览器访问这个地址即可。

## 使用

1. 左侧选择数据来源：先用"合成数据"跑一遍，确认前后端联通没问题
2. 切到"真实A股数据"，选个股票代码（或从下拉框选常见股票），设置日期区间
3. 调整快线/慢线周期、初始资金
4. 点击"运行回测"，右侧会展示：
   - 绩效指标卡片（总收益率、夏普比率、最大回撤、胜率等）
   - K线图，叠加快慢均线，买卖点用红/绿箭头标出
   - 资金曲线
   - 逐笔交易记录表格

## 部署为生产环境（可选）

现在是前后端分离的开发模式。如果想打包成单个服务：

```bash
cd webapp/client
npm run build   # 生成 dist/ 目录
```

然后在 `server.js` 里加一行 `app.use(express.static('../client/dist'))`，
把Node服务器改成同时托管静态前端文件，这样只需要跑一个 `npm start` 就够了。

## 已知限制

- 每次点击"运行回测"都是重新起一个Python进程完整跑一遍，单次真实数据回测大概几秒到十几秒，
  取决于数据量和网络（AkShare请求速度）。如果之后要做参数批量优化（网格搜索），
  这套单次请求的架构会比较慢，需要改造成任务队列 + 进度轮询的模式。
- 目前只接了双均线策略这一种，`server.js` 的 `/api/backtest` 接口是硬编码调用
  `strategy/ma_cross.py`。如果要支持切换策略，需要在Python的 `main.py` 里加
  `--strategy` 参数，Node这边透传即可。
