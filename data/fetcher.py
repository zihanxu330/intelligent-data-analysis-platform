# -*- coding: utf-8 -*-
"""
数据获取模块
- fetch_stock_daily(): 真实A股日线数据，基于AkShare。在有正常互联网访问的环境下可直接使用。
  这个函数专门给 data_engine/downloader.py 用，它才是唯一应该主动联网的地方。
- fetch_stock_daily_local_first(): 策略/回测应该用这个。优先读本地SQLite数据仓库，
  完全不联网；只有本地没有数据时才兜底联网拉一次并顺便存库，方便下次直接读本地。
- generate_synthetic_daily(): 合成数据生成器，用于离线开发/测试回测引擎逻辑，
  不依赖任何真实行情接口。数据服从带漂移和均值回归成分的随机游走，
  用来验证策略/回测链路是否跑通，不代表真实市场规律。
"""
import os
import numpy as np
import pandas as pd


def fetch_stock_daily(symbol: str, start_date: str, end_date: str,
                       adjust: str = "qfq", cache_dir: str = None) -> pd.DataFrame:
    """
    拉取A股日线行情（真实数据源，需要正常互联网环境）。

    参数:
        symbol: 股票代码，如 '600519'（贵州茅台，不带交易所前缀）
        start_date: 'YYYYMMDD'
        end_date:   'YYYYMMDD'
        adjust: 复权方式，'qfq'前复权 / 'hfq'后复权 / '' 不复权
        cache_dir: 若提供，会把结果缓存为csv，避免重复请求（轻量场景用；
                   批量/长期使用建议改用 data_engine.database 的SQLite仓库）

    返回:
        DataFrame，列: date, open, high, low, close, volume, ...（索引重置为0..n）
    """
    import akshare as ak

    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{symbol}_{start_date}_{end_date}_{adjust}.csv")
        if os.path.exists(cache_path):
            return pd.read_csv(cache_path, parse_dates=["date"])

    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start_date, end_date=end_date, adjust=adjust
    )
    # AkShare返回的是中文列名，统一转成英文，方便后续backtrader等库使用
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "换手率": "turnover",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if cache_path:
        df.to_csv(cache_path, index=False)
    return df


def fetch_stock_daily_local_first(symbol: str, start_date: str, end_date: str,
                                   adjust: str = "qfq") -> pd.DataFrame:
    """
    策略/回测代码应该调用这个函数，而不是 fetch_stock_daily。

    优先从本地SQLite数据仓库读取（不联网，不受代理/DNS/杀毒软件/接口限流影响）。
    只有本地完全没有这只股票的数据时，才兜底联网拉取一次，并顺便写入本地库，
    这样下次同一只股票就不用再联网了。

    建议的正常工作流：先用 data_engine/downloader.py 批量下载好数据，
    之后回测/调参无论跑多少次都走本地，这个"兜底联网"分支基本不会触发。
    """
    from data_engine.database import load_daily, has_data, save_daily

    if has_data(symbol):
        df = load_daily(symbol, start_date, end_date)
        if not df.empty:
            return df

    print(f"[提示] 本地库没有 {symbol} 的数据，联网拉取一次并存入本地库...")
    df = fetch_stock_daily(symbol, start_date, end_date, adjust=adjust)
    save_daily(symbol, df)
    return df


def generate_synthetic_daily(n_days: int = 500, start_price: float = 50.0,
                              seed: int = 42, drift: float = 0.0003,
                              vol: float = 0.018, mean_revert: float = 0.02) -> pd.DataFrame:
    """
    生成一条合成的日线数据，结构与fetch_stock_daily返回的DataFrame一致，
    方便在没有网络的环境下测试回测引擎、策略逻辑是否正确。

    价格模型：几何随机游走 + 轻微均值回归项，仅用于工程验证，不用于真实决策。
    """
    rng = np.random.default_rng(seed)
    # 注意：部分pandas版本下 periods=n 实际返回 n-1 个日期，多取几个再裁剪保证长度精确
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days + 5)[-n_days:]

    log_price = np.log(start_price)
    log_ma = log_price
    closes = []
    for _ in range(n_days):
        shock = rng.normal(drift, vol)
        # 轻微向近期均值回归，避免纯随机游走导致的无界发散
        reversion = mean_revert * (log_ma - log_price)
        log_price += shock + reversion
        log_ma = 0.98 * log_ma + 0.02 * log_price
        closes.append(np.exp(log_price))

    closes = np.array(closes)
    opens = closes * (1 + rng.normal(0, 0.003, n_days))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.006, n_days)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.006, n_days)))
    volumes = rng.integers(1_000_000, 8_000_000, n_days)

    df = pd.DataFrame({
        "date": dates, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })
    return df


if __name__ == "__main__":
    df = generate_synthetic_daily()
    print(df.head())
    print(f"共 {len(df)} 条记录，价格区间: {df['close'].min():.2f} ~ {df['close'].max():.2f}")
