# -*- coding: utf-8 -*-
"""纸面买入结算的纯函数（无网络、无数据库、无真实交易）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

COMMISSION = 0.0003
MIN_COMMISSION = 5.0
TRANSFER = 0.00001
SLIPPAGE = 0.001


@dataclass(frozen=True)
class Fill:
    symbol: str
    rule: str
    shares: int
    fill_price: float
    gross: float
    commission: float
    transfer: float
    total_cost: float
    status: str
    reason: str


def buy_fill(symbol: str, rule: str, shares: int, raw_open: Optional[float],
             cash: float, slippage: float = SLIPPAGE) -> Fill:
    """按冻结买入规则计算一笔成交；不修改现金。"""
    shares = int(shares)
    if shares <= 0:
        return Fill(symbol, rule, shares, 0.0, 0.0, 0.0, 0.0, 0.0, "blocked_lot_min", "target_shares <= 0")
    if raw_open is None:
        return Fill(symbol, rule, shares, 0.0, 0.0, 0.0, 0.0, 0.0, "no_target_bar", "raw open missing")
    if raw_open <= 0:
        return Fill(symbol, rule, shares, 0.0, 0.0, 0.0, 0.0, 0.0, "invalid_price", "raw open <= 0")
    price = float(raw_open) * (1.0 + slippage)
    gross = price * shares
    commission = max(MIN_COMMISSION, gross * COMMISSION)
    transfer = gross * TRANSFER
    total = gross + commission + transfer
    if total > cash + 1e-9:
        return Fill(symbol, rule, shares, price, gross, commission, transfer, total, "insufficient_cash", "total cost > cash")
    return Fill(symbol, rule, shares, price, gross, commission, transfer, total, "filled", "")


def settle_book(orders, prices, capital: float = 1_000_000.0):
    """orders: DataFrame-like records with rule/symbol/target_shares/status.
    prices: {symbol: (open, close)}; returns fills, positions, nav, cash, status counts.
    """
    cash = float(capital)
    fills, positions = [], []
    counts = {}
    for o in orders:
        rule = str(o["rule"]); sym = str(o["symbol"]).zfill(6)
        status = str(o.get("status", "pending_no_fill"))
        shares = int(o.get("target_shares", 0) or 0)
        if status == "blocked_lot_min":
            f = buy_fill(sym, rule, 0, None, cash)
            f = Fill(sym, rule, 0, 0, 0, 0, 0, 0, "blocked_lot_min", "frozen blocked_lot_min")
        else:
            op = prices.get(sym, (None, None))[0]
            f = buy_fill(sym, rule, shares, op, cash)
        fills.append(f)
        counts[f.status] = counts.get(f.status, 0) + 1
        if f.status == "filled":
            cash -= f.total_cost
            positions.append({"rule": rule, "symbol": sym, "shares": f.shares,
                              "avg_price": f.fill_price, "cost": f.total_cost})
    mv = 0.0
    for p in positions:
        close = prices.get(p["symbol"], (None, None))[1]
        if close is None:
            p["market_value"] = None
            mv = None
            continue
        p["market_value"] = float(close) * p["shares"]
        if mv is not None:
            mv += p["market_value"]
    return {"fills": fills, "positions": positions, "cash": cash,
            "market_value": mv, "nav": None if mv is None else cash + mv, "counts": counts}
