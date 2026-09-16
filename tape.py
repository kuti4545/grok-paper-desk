"""Funding, 24s range, order book duvari — sadece acik + watch."""

from __future__ import annotations

import config

SESSION = None


def attach_session(session):
    global SESSION
    SESSION = session


def fnum(row, key, default=0.0):
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def last_px(row):
    return float(row.get("lastPr") or row.get("markPrice") or 0)


def chg_pct(row):
    return fnum(row, "change24h") * 100.0


def fetch_book(symbol, limit=15):
    r = SESSION.get(
        f"{config.BITGET_BASE}/api/v2/mix/market/orderbook",
        params={"symbol": symbol, "productType": "usdt-futures", "limit": str(limit)},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "00000":
        return {}
    return body.get("data") or {}


def wall_snapshot(symbol, ticker):
    px = last_px(ticker)
    high = fnum(ticker, "high24h")
    low = fnum(ticker, "low24h")
    span = high - low
    loc = ((px - low) / span * 100) if span else 50
    bid_sz = fnum(ticker, "bidSz")
    ask_sz = fnum(ticker, "askSz")
    imb = ((bid_sz - ask_sz) / (bid_sz + ask_sz) * 100) if (bid_sz + ask_sz) else 0.0
    snap = {
        "symbol": symbol,
        "price": px,
        "change24h": round(chg_pct(ticker), 2),
        "funding_pct": round(fnum(ticker, "fundingRate") * 100, 4),
        "oi": fnum(ticker, "holdingAmount"),
        "vol24_usdt": round(fnum(ticker, "usdtVolume"), 0),
        "range_loc": round(loc, 1),
        "high24": high,
        "low24": low,
        "book_imb": round(imb, 1),
    }
    try:
        depth = fetch_book(symbol)
        asks = [[float(a[0]), float(a[1])] for a in (depth.get("asks") or [])[:15]]
        bids = [[float(b[0]), float(b[1])] for b in (depth.get("bids") or [])[:15]]
        ask_wall = max(asks, key=lambda x: x[1]) if asks else [0, 0]
        bid_wall = max(bids, key=lambda x: x[1]) if bids else [0, 0]
        snap["ask_wall"] = {"price": ask_wall[0], "size": ask_wall[1]}
        snap["bid_wall"] = {"price": bid_wall[0], "size": bid_wall[1]}
    except Exception as exc:
        snap["book_error"] = str(exc)
    return snap


def movers(tickers, skip):
    rows = []
    for sym, row in tickers.items():
        if not sym.endswith("USDT") or sym in skip:
            continue
        if fnum(row, "usdtVolume") < 1_500_000:
            continue
        px = last_px(row)
        if px <= 0:
            continue
        rows.append({
            "symbol": sym,
            "price": px,
            "change24h": round(chg_pct(row), 2),
            "vol24_usdt": round(fnum(row, "usdtVolume"), 0),
            "funding_pct": round(fnum(row, "fundingRate") * 100, 4),
        })
    up = sorted(rows, key=lambda x: x["change24h"], reverse=True)[:7]
    down = sorted(rows, key=lambda x: x["change24h"])[:7]
    return up, down


def enrich(book, tickers):
    symbols = {p["symbol"] for p in book.get("open") or []}
    symbols |= {w.get("symbol") for w in book.get("watch") or [] if w.get("symbol")}
    tape = {}
    for sym in list(symbols)[:12]:
        row = tickers.get(sym)
        if not row:
            continue
        tape[sym] = wall_snapshot(sym, row)
    book["tape"] = tape
    for pos in book.get("open") or []:
        snap = tape.get(pos["symbol"])
        if not snap:
            continue
        pos["funding_pct"] = snap.get("funding_pct")
        pos["range_loc"] = snap.get("range_loc")
        pos["ask_wall"] = snap.get("ask_wall")
        pos["bid_wall"] = snap.get("bid_wall")
    return tape
