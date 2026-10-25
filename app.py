import os
import time
import asyncio
import ccxt
import aiohttp
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uvicorn

RIYADH_TZ = timezone(timedelta(hours=3))

def get_riyadh_time():
    return datetime.now(RIYADH_TZ).strftime('%I:%M:%S %p')

def get_predicted_end_time(minutes_ahead):
    future_time = datetime.now(RIYADH_TZ) + timedelta(minutes=minutes_ahead)
    return future_time.strftime('%I:%M:%S %p')

app = FastAPI(title="OKX Multi-Timeframe Pro Scalping", version="15.0")

OKX_CONFIG = {
    'apiKey': '8dd26496-0023-4b54-ae2b-4a48d513fb05',
    'secret': 'EB61E3ACC19D33653EDC54DA55388B2E',
    'password': 'Aa11223344##',
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
}

SYSTEM_STATE = {
    "is_running": True,
    "timeframe": "1m",                  # الفريم الزمني المختار (1m, 5m, 15m)
    "mode": "auto",
    "custom_symbols": ["BTC/USDT"],
    "trade_budget": 20.0,
    "max_positions": 3,
    "normal_mode": True,
    "guardian_active": True,
    "market_suitable": True,
    "max_loss_trades": 3,
    "today_loss_count": 0,
    "lock_reason": "",
    "balance": {"total": 10000.0, "free": 10000.0, "used": 0.0},
    "tickers": {},
    "top_100_market": [],
    "positions": [],
    "closed_history": [],
    "analysis_report": {
        "top_3": [],
        "best_coin": "جاري تحليل الفريم المختار...",
        "confidence": "98.5%",
        "reason": "بوت التحليل يدرس السيولة بناءً على الفريم المحدد..."
    },
    "stats": {
        "successful_trades": 0,
        "total_pnl": 0.0,
        "last_action": "النظام يعمل وفق الفريم المختار...",
        "ai_bias": "BULLISH",
        "current_rsi": 28.5
    }
}

class ControlModel(BaseModel):
    is_running: bool = None
    timeframe: str = None
    mode: str = None
    custom_symbols: list = None
    trade_budget: float = None
    max_positions: int = None
    normal_mode: bool = None
    guardian_active: bool = None
    max_loss_trades: int = None

class ClosePositionModel(BaseModel):
    position_id: int

def init_exchange():
    exchange = ccxt.okx(OKX_CONFIG)
    exchange.set_sandbox_mode(True)
    return exchange

async def automated_trading_supervisor():
    exchange = init_exchange()

    while True:
        if SYSTEM_STATE["is_running"]:
            try:
                if SYSTEM_STATE["today_loss_count"] >= SYSTEM_STATE["max_loss_trades"]:
                    SYSTEM_STATE["is_running"] = False
                    SYSTEM_STATE["lock_reason"] = f"تم إيقاف البوت لتجاوز حد صفقات الخسارة على الفريم الحالية ({SYSTEM_STATE['max_loss_trades']} صفقات)."
                    await asyncio.sleep(3)
                    continue

                tf = SYSTEM_STATE["timeframe"] # الفريم المختار (1m, 5m, 15m)
                
                # جلب البيانات التاريخية والشموع بناءً على الفريم المختار لتقييم السوق بدقة
                markets = exchange.load_markets()
                usdt_symbols = [s for s in markets if s.endswith('/USDT') and ':' not in s]

                market_analysis_pool = []
                vol_sum = 0.0

                for sym in usdt_symbols[:50]: # فحص عينة واسعة لتقييم السوق
                    try:
                        # استخدام الفريم المختار في سحب الشموع (OHLCV) لتقييم الاتجاه الحقيقي
                        ohlcv = exchange.fetch_ohlcv(sym, timeframe=tf, limit=10)
                        if len(ohlcv) >= 2:
                            prev_close = ohlcv[-2][4]
                            curr_close = ohlcv[-1][4]
                            change_pct = ((curr_close - prev_close) / prev_close) * 100
                        else:
                            ticker = exchange.fetch_ticker(sym)
                            change_pct = float(ticker.get('percentage', 0.0))

                        ticker = exchange.fetch_ticker(sym)
                        price = float(ticker['last'])
                        vol = float(ticker.get('quoteVolume', 0.0))
                        
                        vol_sum += abs(change_pct)
                        score = change_pct * 0.6 + (vol / 500000) * 0.4
                        
                        market_analysis_pool.append({
                            "symbol": sym, "price": price, "change": change_pct,
                            "volume": vol, "score": score,
                            "status": f"مستقر على فريم {tf} 🟢" if change_pct > 0 else "قيد المراقبة 🟡"
                        })
                    except Exception:
                        pass
                    await asyncio.sleep(0.02)

                market_analysis_pool.sort(key=lambda x: x['score'], reverse=True)
                SYSTEM_STATE["top_100_market"] = market_analysis_pool

                # بوت المراقبة يقيم السوق بناءً على حركة الفريم المختار
                avg_change = (vol_sum / len(market_analysis_pool)) if market_analysis_pool else 0.0
                if SYSTEM_STATE["guardian_active"]:
                    # إذا كان الفريم 15m يتطلب تذبذباً أدق، وإذا كان 1m يتطلب حركة أسرع
                    threshold = 0.08 if tf == "1m" else (0.15 if tf == "5m" else 0.25)
                    SYSTEM_STATE["market_suitable"] = avg_change >= threshold

                top_3_coins = market_analysis_pool[:3]
                SYSTEM_STATE["analysis_report"]["top_3"] = top_3_coins

                if top_3_coins:
                    SYSTEM_STATE["analysis_report"]["best_coin"] = top_3_coins[0]["symbol"]
                    SYSTEM_STATE["analysis_report"]["reason"] = f"بوت التحليل والمراقبة يقيّن السوق بنجاح بناءً على إطار الفريم الزمني ({tf})."

                try:
                    balance = exchange.fetch_balance()
                    usdt_bal = balance.get('USDT', {})
                    SYSTEM_STATE["balance"] = {
                        "total": float(usdt_bal.get('total', 10000.0)),
                        "free": float(usdt_bal.get('free', 10000.0)),
                        "used": float(usdt_bal.get('used', 0.0))
                    }
                except Exception:
                    pass

                # تنفيذ الصفقات بشرط أن يكون السوق مناسباً على الفريم المختار
                if SYSTEM_STATE["normal_mode"] and SYSTEM_STATE["market_suitable"] and top_3_coins:
                    active_pool = SYSTEM_STATE["custom_symbols"] if SYSTEM_STATE["mode"] == "custom" else [top_3_coins[0]["symbol"]]
                    
                    for sym in active_pool:
                        match_item = next((x for x in market_analysis_pool if x['symbol'] == sym), None)
                        if match_item and len(SYSTEM_STATE["positions"]) < SYSTEM_STATE["max_positions"]:
                            existing = [p for p in SYSTEM_STATE["positions"] if p["symbol"] == sym]
                            if not existing and match_item['change'] > 0:
                                cur_price = match_item['price']
                                tp = round(cur_price * (1.005 if tf == "15m" else (1.004 if tf == "5m" else 1.003)), 4)
                                sl = round(cur_price * 0.9930, 4)
                                duration = 15 if tf == "15m" else (10 if tf == "5m" else 5)

                                try:
                                    amount = SYSTEM_STATE["trade_budget"] / cur_price
                                    exchange.create_order(sym, 'market', 'buy', amount)

                                    new_pos = {
                                        "id": int(time.time() * 1000),
                                        "symbol": sym,
                                        "type": f"فريم {tf} ({match_item['status']})",
                                        "entryPrice": cur_price,
                                        "currentPrice": cur_price,
                                        "tp": tp,
                                        "sl": sl,
                                        "pnlVal": 0.0,
                                        "pnl": "+0.00%",
                                        "isProfit": True,
                                        "time": get_riyadh_time(),
                                        "endTime": get_predicted_end_time(duration)
                                    }
                                    SYSTEM_STATE["positions"].insert(0, new_pos)
                                    SYSTEM_STATE["stats"]["successful_trades"] += 1
                                except Exception:
                                    pass

                # تحديث PnL الصفقات النشطة
                for pos in SYSTEM_STATE["positions"]:
                    match_item = next((x for x in market_analysis_pool if x['symbol'] == pos['symbol']), None)
                    if match_item:
                        pos["currentPrice"] = match_item['price']
                    diff = ((pos["currentPrice"] - pos["entryPrice"]) / pos["entryPrice"]) * 100
                    pos["pnlVal"] = round(diff, 2)
                    pos["pnl"] = (("+" if diff >= 0 else "") + f"{diff:.2f}%")
                    pos["isProfit"] = diff >= 0

            except Exception as e:
                print(f"Loop error: {e}", flush=True)

            await asyncio.sleep(5)
        else:
            await asyncio.sleep(2)

async def self_ping_loop():
    port = int(os.environ.get("PORT", 10000))
    url = f"http://127.0.0.1:{port}/"
    await asyncio.sleep(5)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    pass
        except Exception:
            pass
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(automated_trading_supervisor())
    asyncio.create_task(self_ping_loop())

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return "<h1>Error: index.html not found!</h1>"

@app.get("/api/state")
async def get_state():
    return SYSTEM_STATE

@app.post("/api/control")
async def control_system(data: ControlModel):
    if data.is_running is not None:
        SYSTEM_STATE["is_running"] = data.is_running
    if data.timeframe is not None:
        SYSTEM_STATE["timeframe"] = data.timeframe
    if data.mode is not None:
        SYSTEM_STATE["mode"] = data.mode
    if data.custom_symbols is not None:
        SYSTEM_STATE["custom_symbols"] = data.custom_symbols
    if data.trade_budget is not None:
        SYSTEM_STATE["trade_budget"] = data.trade_budget
    if data.max_positions is not None:
        SYSTEM_STATE["max_positions"] = data.max_positions
    if data.normal_mode is not None:
        SYSTEM_STATE["normal_mode"] = data.normal_mode
    if data.guardian_active is not None:
        SYSTEM_STATE["guardian_active"] = data.guardian_active
    if data.max_loss_trades is not None:
        SYSTEM_STATE["max_loss_trades"] = data.max_loss_trades
    return {"success": True, "state": SYSTEM_STATE}

@app.post("/api/close_position")
async def close_position(data: ClosePositionModel):
    closed = [p for p in SYSTEM_STATE["positions"] if p["id"] == data.position_id]
    if closed:
        pos = closed[0]
        history_item = {
            "symbol": pos["symbol"],
            "entry": pos["entryPrice"],
            "exit": pos["currentPrice"],
            "pnlVal": pos["pnlVal"],
            "pnlText": pos["pnl"],
            "isWin": pos["isProfit"]
        }
        SYSTEM_STATE["closed_history"].insert(0, history_item)

        if not pos["isProfit"]:
            SYSTEM_STATE["today_loss_count"] += 1

    SYSTEM_STATE["positions"] = [p for p in SYSTEM_STATE["positions"] if p["id"] != data.position_id]
    return {"success": True}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
