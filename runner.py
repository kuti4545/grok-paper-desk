#!/usr/bin/env python3
"""5 dk: fiyat guncelle, Grok kararini deftere yaz, SL/TP uygula, Telegram."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import requests

import config

TR = timezone(timedelta(hours=3))
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "grok-paper-desk/1.0"})


def now() -> datetime:
    return datetime.now(TR)


def iso() -> str:
    return now().isoformat(timespec="seconds")


def load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: str, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_book() -> dict:
    book = load_json(config.BOOK_PATH, {})
    book.setdefault("start_equity", config.START_EQUITY)
    book.setdefault("open", [])
    book.setdefault("closed", [])
    book.setdefault("log", [])
    book.setdefault("processed_decision", "")
    return book


def send_telegram(text: str) -> None:
    token, chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
    if not token or not chat:
        print("telegram yok:\n", text)
        return
    try:
        SESSION.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
    except requests.RequestException as exc:
        print("telegram", exc)


def fetch_tickers() -> dict:
    r = SESSION.get(
        f"{config.BITGET_BASE}/api/v2/mix/market/tickers",
        params={"productType": config.PRODUCT_TYPE},
        timeout=20,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "00000":
        raise RuntimeError(body)
    return {row["symbol"]: row for row in (body.get("data") or []) if row.get("symbol")}


def last_px(row: dict) -> float:
    return float(row.get("lastPr") or 0)


def fetch_scanner() -> dict:
    url = config.SCANNER_JSON
    if url.startswith("http"):
        req = Request(url, headers={"User-Agent": "grok-paper-desk/1.0"})
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    path = Path(url)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pnl_usdt(side: str, entry: float, mark: float, notional: float) -> float:
    if not entry:
        return 0.0
    move = (mark - entry) / entry
    if side == "SHORT":
        move = -move
    return notional * move


def close_pos(book: dict, pos: dict, mark: float, reason: str) -> None:
    pos["exit"] = mark
    pos["closed_at"] = iso()
    pos["result"] = reason
    pos["pnl"] = round(pnl_usdt(pos["side"], pos["entry"], mark, pos["notional"]), 4)
    book["closed"].append(pos)
    book["open"] = [p for p in book["open"] if p.get("id") != pos.get("id")]
    send_telegram(
        f"Grok kapatti ({reason})\n{pos['side']} {pos['symbol']}\n"
        f"Giris {pos['entry']} -> cikis {mark}\nPnL {pos['pnl']:+.2f} USDT"
    )


def mark_and_stops(book: dict, tickers: dict) -> list:
    notes = []
    for pos in list(book.get("open") or []):
        row = tickers.get(pos["symbol"])
        if not row:
            continue
        mark = last_px(row)
        pos["mark"] = mark
        pos["pnl"] = round(pnl_usdt(pos["side"], pos["entry"], mark, pos["notional"]), 4)
        pos["pnl_pct"] = round((pos["pnl"] / pos["margin"]) * 100, 2) if pos.get("margin") else 0
        sl, tp = float(pos["sl"]), float(pos["tp"])
        hit = None
        if pos["side"] == "LONG":
            if sl and mark <= sl:
                hit = "SL"
            elif tp and mark >= tp:
                hit = "TP"
        else:
            if sl and mark >= sl:
                hit = "SL"
            elif tp and mark <= tp:
                hit = "TP"
        if hit:
            close_pos(book, pos, mark, hit)
            notes.append(f"{hit} {pos['symbol']} {pos['pnl']:+.2f}")
    return notes


def apply_decision(book: dict, tickers: dict) -> list:
    decision = load_json(config.DECISION_PATH, {})
    did = str(decision.get("id") or "")
    if not did or did == book.get("processed_decision"):
        return []
    notes = []
    book["last_thought"] = decision.get("commentary") or ""
    book["last_thought_at"] = decision.get("created_at") or iso()
    for item in decision.get("exits") or []:
        symbol = str(item.get("symbol") or "").upper()
        reason = item.get("reason") or "Grok cikis"
        for pos in list(book.get("open") or []):
            if pos["symbol"] != symbol:
                continue
            row = tickers.get(symbol)
            mark = last_px(row) if row else float(pos.get("mark") or pos["entry"])
            close_pos(book, pos, mark, reason)
            notes.append(f"Grok cikis {symbol}")
    for item in decision.get("entries") or []:
        symbol = str(item.get("symbol") or "").upper()
        side = str(item.get("side") or "").upper()
        if symbol in config.SKIP_SYMBOLS or side not in {"LONG", "SHORT"}:
            continue
        if any(p["symbol"] == symbol for p in book.get("open") or []):
            notes.append(f"{symbol} zaten acik")
            continue
        if len(book.get("open") or []) >= config.MAX_OPEN:
            notes.append("max acik")
            break
        row = tickers.get(symbol)
        if not row:
            continue
        entry = last_px(row)
        sl = float(item.get("sl") or 0)
        tp = float(item.get("tp") or 0)
        if side == "LONG":
            sl = sl or entry * 0.988
            tp = tp or entry * 1.02
        else:
            sl = sl or entry * 1.012
            tp = tp or entry * 0.98
        lev = max(1, min(config.MAX_LEVERAGE, int(item.get("leverage") or 2)))
        margin = config.MARGIN_PER_TRADE
        pos = {
            "id": uuid.uuid4().hex[:10],
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "mark": entry,
            "sl": sl,
            "tp": tp,
            "leverage": lev,
            "margin": margin,
            "notional": margin * lev,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "score": item.get("score"),
            "setup": item.get("setup"),
            "thesis": item.get("thesis") or decision.get("commentary") or "",
            "opened_at": iso(),
            "source": "grok",
            "decision_id": did,
        }
        book["open"].append(pos)
        send_telegram(
            f"Grok giriyor\n{side} {symbol}  {lev}x\nGiris {entry}\nSL {sl}\nTP {tp}\n{pos['thesis'][:280]}"
        )
        notes.append(f"Grok giris {side} {symbol} {entry}")
    book["processed_decision"] = did
    return notes


def candidates(scan: dict) -> list:
    out = []
    for s in scan.get("top") or []:
        if float(s.get("score") or 0) < config.CANDIDATE_SCORE:
            continue
        if s.get("symbol") in config.SKIP_SYMBOLS:
            continue
        out.append({
            "symbol": s.get("symbol"),
            "side": s.get("direction"),
            "score": s.get("score"),
            "price": s.get("price"),
            "sl": s.get("sl"),
            "tp": s.get("tp1"),
            "setup": s.get("setup"),
            "style": s.get("style"),
            "rsi": s.get("rsi"),
            "confidence": s.get("confidence"),
            "yorum": s.get("yorum"),
        })
    return out[:7]


def summarize(book: dict) -> dict:
    closed = book.get("closed") or []
    wins = [p for p in closed if float(p.get("pnl") or 0) > 0]
    realized = sum(float(p.get("pnl") or 0) for p in closed)
    floating = sum(float(p.get("pnl") or 0) for p in book.get("open") or [])
    start = float(book.get("start_equity") or config.START_EQUITY)
    equity = start + realized + floating
    return {
        "updated_at": iso(),
        "start_equity": start,
        "equity": round(equity, 2),
        "realized": round(realized, 2),
        "floating": round(floating, 2),
        "pnl": round(equity - start, 2),
        "pnl_pct": round(((equity - start) / start) * 100, 2) if start else 0,
        "open_count": len(book.get("open") or []),
        "closed_count": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "indicators": config.INDICATORS,
        "mode": "SANAL * giris/cikis Grok",
    }


def main() -> None:
    book = load_book()
    tickers = fetch_tickers()
    notes = []
    notes += apply_decision(book, tickers)
    notes += mark_and_stops(book, tickers)
    scan = {}
    try:
        scan = fetch_scanner()
    except Exception as exc:
        notes.append(f"tarayici: {exc}")
    book["candidates"] = candidates(scan)
    book["scan_at"] = scan.get("updated_at")
    book["scanned"] = scan.get("scanned")
    book["stats"] = summarize(book)
    if notes:
        book["log"].append({"ts": iso(), "events": notes})
        book["log"] = book["log"][-80:]
    save_json(config.BOOK_PATH, book)
    print(json.dumps(book["stats"], ensure_ascii=False))
    for n in notes:
        print(n)


if __name__ == "__main__":
    main()
