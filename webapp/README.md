# Quant Research Web dashboard

React 看板通过 Node.js API 调用仓库根目录的 `main.py`，展示 K 线、资金曲线、指标和逐笔交易。

## Setup

先按 [仓库 README](../README.md#quick-start) 创建 Python 虚拟环境并安装离线演示依赖。真实行情和模型研究另需完整依赖。

从仓库根目录，在两个终端分别启动服务：

### API · terminal 1

```bash
cd webapp/server
npm ci
npm start
```

API 位于 [http://localhost:3001](http://localhost:3001)，健康检查为 `GET /api/health`。

Node 默认调用系统的 `python`（Windows）或 `python3`（macOS/Linux）。请先激活项目虚拟环境，或通过 `PYTHON_BIN` 指定该环境中的解释器。PowerShell 示例：

```powershell
$env:PYTHON_BIN = (Resolve-Path .venv/Scripts/python.exe).Path
cd webapp/server
npm start
```

上面的 PowerShell 命令从仓库根目录执行。

### React · terminal 2

```bash
cd webapp/client
npm ci
npm run dev
```

打开 Vite 输出的网址，通常为 [http://localhost:5173](http://localhost:5173)。界面默认选择“合成数据”，点击“运行回测”即可验证链路。

## Checks

客户端目录：`npm run lint`、`npm run build`。

构建产物位于 `webapp/client/dist/`。当前 Node 服务只提供 API，不会自动托管构建目录。

## Boundaries

- 每次回测启动一个 Python 子进程；尚无后台任务队列。
- Web 表单透传数据模式、日期、初始资金和快慢均线参数，使用默认规则策略。
- 真实数据模式可能联网并写入本地数据库；合成数据用于离线工程验证。
- 这是本地研究面板，尚无认证、用户隔离或公网部署配置。
