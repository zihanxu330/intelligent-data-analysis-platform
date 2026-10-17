# -*- coding: utf-8 -*-
"""
CLI/API统一入口。
- CLI用法（人工调试）: python main.py --mode synthetic
- API用法（webapp/server/server.js 调用）: python main.py --mode real --symbol 600519
  --start 20230101 --end 20241231 --cash 100000 --fast-period 10 --slow-period 30
  --json-out output/api_runs/xxx.json --no-plot
"""
import argparse
import json
import math
import os
import re
from datetime import datetime

from data.fetcher import generate_synthetic_daily, fetch_stock_daily_local_first
from backtest.engine import run_backtest
from strategy.ma_cross import MACrossStrategy
from strategy.ai_decision import AIDecisionStrategy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='synthetic', choices=['synthetic', 'real'],
                         help="synthetic=合成数据（离线测试）, real=真实A股数据（本地优先，联网兜底）")
    parser.add_argument('--strategy', default='rule', choices=['rule', 'ai'],
                         help="rule=多因子规则决策（默认）, ai=纯AI模型决策（买卖全由模型预测概率决定）")
    parser.add_argument('--symbol', default='600519')
    parser.add_argument('--start', default='20230101')
    parser.add_argument('--end', default='20241231')
    parser.add_argument('--cash', type=float, default=100000.0)
    parser.add_argument('--fast-period', type=int, default=10, dest='fast_period')
    parser.add_argument('--slow-period', type=int, default=30, dest='slow_period')
    parser.add_argument('--json-out', default=None, dest='json_out',
                         help="若提供路径，把完整回测结果写成JSON（供server.js读取）")
    parser.add_argument('--no-plot', action='store_true', dest='no_plot',
                         help="不生成资金曲线png（API模式下不需要落图，加快速度）")
    parser.add_argument('--use-ai', action='store_true', dest='use_ai',
                         help="规则策略下启用AI过滤：规则信号成立后还要模型预测上涨概率够高才买入")
    parser.add_argument('--ai-model', default='output/model_updown.joblib', dest='ai_model',
                         help="train_model.py 训练产出的模型路径，配合 --use-ai / --strategy ai 使用")
    parser.add_argument('--ai-threshold', type=float, default=0.55, dest='ai_threshold',
                         help="AI过滤阈值，模型预测上涨概率需高于此值才放行买入")
    args = parser.parse_args()

    if not math.isfinite(args.cash) or args.cash <= 0:
        parser.error('--cash 必须是大于0的有限数值')
    if args.strategy == 'rule' and (args.fast_period < 1 or args.slow_period < 2
                                    or args.fast_period >= args.slow_period):
        parser.error('--fast-period 和 --slow-period 必须为正整数，且快线小于慢线')
    if not math.isfinite(args.ai_threshold) or not 0 <= args.ai_threshold <= 1:
        parser.error('--ai-threshold 必须在 0 到 1 之间')
    if not re.fullmatch(r'\d{8}', args.start) or not re.fullmatch(r'\d{8}', args.end):
        parser.error('--start 和 --end 必须使用 YYYYMMDD 格式')
    try:
        start_date = datetime.strptime(args.start, '%Y%m%d').date()
        end_date = datetime.strptime(args.end, '%Y%m%d').date()
    except ValueError:
        parser.error('--start 或 --end 不是有效日期')
    if start_date > end_date:
        parser.error('--start 不能晚于 --end')
    if args.mode == 'real' and not re.fullmatch(r'\d{6}', args.symbol):
        parser.error('--mode real 时 --symbol 必须是6位股票代码')

    os.makedirs('output', exist_ok=True)

    if args.mode == 'synthetic':
        print('[数据] 合成数据模式')
        df = generate_synthetic_daily(800)
    else:
        print(f'[数据] 真实数据模式（本地优先）: {args.symbol} {args.start}~{args.end}')
        df = fetch_stock_daily_local_first(args.symbol, args.start, args.end)

    if df is None or df.empty:
        raise SystemExit('没有获取到行情数据，请检查股票代码、日期范围或本地数据/网络连接。')

    print('[数据]', len(df), '条')

    plot_path = None if args.no_plot else 'output/equity_curve.png'

    if args.strategy == 'ai':
        # 纯AI决策：买卖全由模型预测概率决定，必须加载模型
        strategy_cls = AIDecisionStrategy
        strategy_kwargs = {
            'buy_threshold': args.ai_threshold,
            'sell_threshold': 0.45,
            'max_position': 0.7,
        }
        ai_model_path = args.ai_model
        print('[策略] 纯AI模型决策 (AIDecisionStrategy)，模型:', ai_model_path)
    else:
        # 规则决策：多因子趋势规则，可选加AI过滤
        strategy_cls = MACrossStrategy
        strategy_kwargs = {
            'fast_period': args.fast_period,
            'slow_period': args.slow_period,
            'use_ai_filter': args.use_ai,
            'ai_prob_threshold': args.ai_threshold,
        }
        ai_model_path = args.ai_model if args.use_ai else None
        print('[策略] 多因子规则决策 (MACrossStrategy)'
              + (' + AI过滤' if args.use_ai else ''))

    result = run_backtest(
        df,
        strategy_cls=strategy_cls,
        strategy_kwargs=strategy_kwargs,
        initial_cash=args.cash,
        plot_path=plot_path,
        ai_model_path=ai_model_path,
        symbol=args.symbol,
    )

    print(result['metrics'])
    print('trades', len(result['trades']))

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out) or '.', exist_ok=True)
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)
        print(f'[输出] 结果已写入 {args.json_out}')


if __name__ == '__main__':
    main()
