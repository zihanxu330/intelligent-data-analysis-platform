# -*- coding: utf-8 -*-
"""
批量下载脚本：唯一需要联网的地方。

数据源：iTick官方API（见 data/itick_fetcher.py），不再用AkShare，
避免了之前反复遇到的安全软件/网络层拦截问题。
免费套餐限制：每分钟5次调用、历史数据大约只保留到最近14个月左右（更早的拉不到）。

用法：
    # 下载指定股票
    python -m data_engine.downloader --symbols 600519,000001 --start 20241124 --end 20261231

    # 下载全市场前N只（第一次跑建议先用小的N测试网络是否稳定）
    python -m data_engine.downloader --top 50 --start 20241124 --end 20261231

    # 增量更新：本地库里已有的股票，只补到今天，不用全量重拉
    python -m data_engine.downloader --update-existing

跑之前记得先设置好token：  set ITICK_TOKEN=你的token

跑完之后，回测/策略代码全部从 data_engine.database.load_daily() 读数据，
不再依赖这个脚本运行时的网络状况。
"""
import argparse
import time
from datetime import datetime

from data.itick_fetcher import fetch_stock_daily_itick
from data_engine.database import save_daily, has_data, latest_date, list_symbols
from data_engine.stock_list import get_stock_list

# 免费套餐每分钟5次调用，13秒/次留了一点余量，避免卡在限流边缘
DEFAULT_SLEEP = 13.0
# 免费套餐历史数据大约只能拉到这个日期之前，更早的默认不再往前拉了
DEFAULT_EARLIEST_START = "20241124"


def download_one(symbol: str, start: str, end: str, retry: int = 3, sleep: float = 1.0) -> bool:
    """下载单只股票，带重试和退避。成功返回True。"""
    for attempt in range(1, retry + 1):
        try:
            df = fetch_stock_daily_itick(symbol, start, end, sleep_between_pages=sleep)
            n = save_daily(symbol, df)
            print(f"[OK] {symbol} 写入 {n} 条 ({start}~{end})")
            return True
        except Exception as e:
            print(f"[重试 {attempt}/{retry}] {symbol} 失败: {e}")
            if attempt < retry:
                time.sleep(sleep * attempt)  # 简单线性退避
    print(f"[失败] {symbol} 重试{retry}次后放弃，跳过")
    return False


def download_batch(symbols: list, start: str, end: str, retry: int = 3,
                    sleep_between: float = DEFAULT_SLEEP, skip_existing: bool = False):
    ok, fail = 0, 0
    for i, symbol in enumerate(symbols, 1):
        if skip_existing and has_data(symbol):
            print(f"[跳过 {i}/{len(symbols)}] {symbol} 本地已有数据")
            continue
        print(f"[{i}/{len(symbols)}] 下载 {symbol} ...")
        if download_one(symbol, start, end, retry=retry, sleep=sleep_between):
            ok += 1
        else:
            fail += 1
        time.sleep(sleep_between)  # 免费套餐限速每分钟5次，这里控制节奏避免超限
    print(f"\n===== 下载完成: 成功 {ok}, 失败 {fail} =====")


def update_existing(retry: int = 3, sleep_between: float = DEFAULT_SLEEP):
    """增量更新：本地库里已有的股票，只补最新数据到今天。"""
    symbols = list_symbols()
    today = datetime.now().strftime("%Y%m%d")
    print(f"本地库里共有 {len(symbols)} 只股票，开始增量更新至 {today}")
    for i, symbol in enumerate(symbols, 1):
        last = latest_date(symbol)
        start = last.replace("-", "") if last else DEFAULT_EARLIEST_START
        print(f"[{i}/{len(symbols)}] {symbol} 从 {start} 补到 {today}")
        download_one(symbol, start, today, retry=retry, sleep=sleep_between)
        time.sleep(sleep_between)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default=None, help="逗号分隔的股票代码，如 600519,000001")
    parser.add_argument("--top", type=int, default=None, help="从全市场股票列表取前N只下载")
    parser.add_argument("--start", type=str, default=DEFAULT_EARLIEST_START,
                         help="免费套餐历史数据大约只能拉到2024-11-24左右，更早的拉不到")
    parser.add_argument("--end", type=str, default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                         help="每只股票之间的等待秒数，免费套餐每分钟5次调用，别调太小")
    parser.add_argument("--skip-existing", action="store_true", help="本地已有数据的股票跳过，不重新下载")
    parser.add_argument("--update-existing", action="store_true", help="只增量更新本地库里已有的股票到最新")
    args = parser.parse_args()

    if args.update_existing:
        update_existing(retry=args.retry, sleep_between=args.sleep)
        return

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.top:
        stock_list = get_stock_list()
        code_col = "code" if "code" in stock_list.columns else stock_list.columns[0]
        symbols = stock_list[code_col].astype(str).tolist()[: args.top]
    else:
        parser.error("请指定 --symbols、--top 或 --update-existing 其中之一")
        return

    download_batch(symbols, args.start, args.end, retry=args.retry,
                    sleep_between=args.sleep, skip_existing=args.skip_existing)


if __name__ == "__main__":
    main()
