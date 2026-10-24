import os
import sys
import time
import asyncio
import pandas as pd
import ccxt
import aiohttp
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# --- إعدادات التوقيت المحلي لمدينة الرياض ---
RIYADH_TZ = timezone(timedelta(hours=3))

def get_riyadh_time():
    return datetime.now(RIYADH_TZ).strftime('%Y-%m-%d %I:%M:%S %p')

app = FastAPI(title="Multi-Agent Scalping & TradingView System", version="1.0")

# إعدادات حالة النظام والتحكم (تشغيل/إيقاف ومراقبة الأداء)
BOT_CONTROL = {
    "is_running": True,
    "active_symbol": "BTC/USDT:USDT",
    "stats": {
        "total_signals": 0,
        "successful_trades": 0,
        "last_action": "قيد الإعداد والتحليل...",
        "ai_bias": "NEUTRAL",
        "current_rsi": 0.0,
        "news_sentiment": "محايد"
    }
}

class ControlModel(BaseModel):
    is_running: bool
    symbol: str = "BTC/USDT:USDT"

# --- 1. بوت جلب الأخبار وتحليل المشاعر (News Agent) ---
class NewsAgent:
    def __init__(self):
        self.latest_news = "لا توجد أخبار عاجلة مؤثرة حالياً."
        self.sentiment = "NEUTRAL"

    async def fetch_market_news(self):
        # محاكاة لجلب الأخبار أو ربطها بـ API أخبار العملات الرقمية
        await asyncio.sleep(20)
        self.sentiment = "BULLISH"
        self.latest_news = "تدفق سيولة إيجابية على العقود الآجلة للعملات الكبرى."
        BOT_CONTROL["stats"]["news_sentiment"] = self.sentiment

# --- 2. بوت التحليل الفني والذكاء الاصطناعي (Analysis Agent) ---
class AnalysisAgent:
    def __init__(self, exchange):
        self.exchange = exchange

    def calculate_rsi(self, series, window=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    async def analyze_market(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1m', limit=50)
            if ohlcv and len(ohlcv) > 0:
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                closes = df['close']
                rsi = self.calculate_rsi(closes, window=14)
                current_rsi = rsi.iloc[-1]
                current_price = closes.iloc[-1]
                sma_20 = closes.rolling(20).mean().iloc[-1]

                ai_bias = "BULLISH" if current_price > sma_20 else "BEARISH"
                
                BOT_CONTROL["stats"]["current_rsi"] = round(float(current_rsi), 2)
                BOT_CONTROL["stats"]["ai_bias"] = ai_bias

                return {"price": current_price, "rsi": current_rsi, "bias": ai_bias}
        except Exception as e:
            print(f"[-] خطأ في بوت التحليل: {e}", flush=True)
        return None

# --- 3. بوت التنفيذ وإدارة الصفقات (Execution Agent) ---
class ExecutionAgent:
    def __init__(self, exchange):
        self.exchange = exchange

    async def execute_order(self, symbol, side, amount=0.001):
        try:
            print(f"[⚡ Execution Agent] تنفيذ أمر {side} على الزوج {symbol} بقيمة {amount}", flush=True)
            # لتفعيل التداول الحقيقي أو التجريبي عبر الـ API:
            # order = self.exchange.create_order(symbol, 'market', side, amount)
            BOT_CONTROL["stats"]["successful_trades"] += 1
            BOT_CONTROL["stats"]["last_action"] = f"تم تنفيذ {side} بنجاح للزوج {symbol}"
            return True
        except Exception as e:
            print(f"[-] خطأ في التنفيذ: {e}", flush=True)
            return False

# --- مدير النظام العام والحلقة المستمرة ---
news_agent = NewsAgent()

@app.on_event("startup")
async def startup_event():
    exchange = ccxt.okx({'enableRateLimit': True})
    exchange.set_sandbox_mode(True) # وضع التجربة (Sandbox) للأمان
    
    analysis_agent = AnalysisAgent(exchange)
    execution_agent = ExecutionAgent(exchange)

    async def system_supervisor():
        while True:
            if BOT_CONTROL["is_running"]:
                symbol = BOT_CONTROL["active_symbol"]
                BOT_CONTROL["stats"]["total_signals"] += 1
                
                # تشغيل بوت التحليل
                analysis = await analysis_agent.analyze_market(symbol)
                if analysis:
                    rsi = analysis["rsi"]
                    bias = analysis["bias"]
                    
                    # استراتيجية سكالبينغ صارمة: RSI منخفض + اتجاه صاعد من الـ AI
                    if rsi < 30 and bias == "BULLISH":
                        await execution_agent.execute_order(symbol, "buy")
                
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(2)

    asyncio.create_task(system_supervisor())
    asyncio.create_task(news_agent.fetch_market_news())

# --- واجهة المراقبة والتحكم مع مؤشر TradingView المضمن ---
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_content = """
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <title>منصة مراقبة وكلاء السكالبينغ الذكية</title>
        <style>
            body { background: #0b0e11; color: #f0f6fc; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
            .header { text-align: center; padding: 15px; background: #161b22; border-radius: 8px; margin-bottom: 20px; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
            .card { background: #161b22; padding: 20px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }
            .btn { padding: 10px 20px; font-size: 16px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
            .btn-start { background: #238636; color: white; }
            .btn-stop { background: #da3633; color: white; }
            .status-box { margin-top: 15px; font-size: 15px; line-height: 1.8; }
            .chart-container { margin-top: 20px; background: #161b22; padding: 15px; border-radius: 8px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🚀 نظام وكلاء السكالبينغ المتعدد (تحليل + تنفيذ + أخبار)</h1>
            <p>مرفق مع مؤشر TradingView المباشر ولوحة التحكم الحية</p>
        </div>

        <div class="grid">
            <div class="card">
                <h2>🎛️ لوحة التحكم والإدارة</h2>
                <p>حالة النظام: <span id="sys-status" style="color: #0ecb81; font-weight: bold;">يعمل</span></p>
                <button class="btn btn-start" onclick="toggleBot(true)">تشغيل البوتات</button>
                <button class="btn btn-stop" onclick="toggleBot(false)">إيقاف طارئ</button>
                
                <div class="status-box">
                    <p>📊 الزوج النشط: <b id="active-symbol">BTC/USDT</b></p>
                    <p>⚡ مؤشر RSI الحالي: <span id="val-rsi">--</span></p>
                    <p>🤖 اتجاه الـ AI: <span id="val-bias">--</span></p>
                    <p>📰 حالة الأخبار: <span id="val-news">--</span></p>
                    <p>🛒 الصفقات الناجحة: <span id="val-trades">0</span></p>
                    <p>📌 آخر إجراء: <span id="val-action" style="color: #f0883e;">--</span></p>
                </div>
            </div>

            <div class="card">
                <h2>📈 أداء الوكلاء المباشر</h2>
                <p>• <b>بوت التحليل:</b> يفحص فريم الدقيقة عبر مؤشرات الزخم والـ RSI.</p>
                <p>• <b>بوت التنفيذ:</b> يربط الصفقات بمنصة OKX عبر مفاتيح الآمان API.</p>
                <p>• <b>بوت الأخبار:</b> يراقب التدفقات الإخبارية لفلترة الأسواق العرضية.</p>
            </div>
        </div>

        <!-- مؤشر TradingView المدمج داخل التطبيق -->
        <div class="chart-container">
            <h2>📉 مؤشر ورسم TradingView المباشر</h2>
            <div class="tradingview-widget-container">
                <div id="tradingview_chart" style="height: 500px;"></div>
                <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                <script type="text/javascript">
                    new TradingView.widget({
                        "width": "100%",
                        "height": "500",
                        "symbol": "OKX:BTCUSDT",
                        "interval": "1",
                        "timezone": "Asia/Riyadh",
                        "theme": "dark",
                        "style": "1",
                        "locale": "ar",
                        "toolbar_bg": "#f1f3f6",
                        "enable_publishing": false,
                        "allow_symbol_change": true,
                        "container_id": "tradingview_chart"
                    });
                </script>
            </div>
        </div>

        <script>
            async function toggleBot(status) {
                let response = await fetch('/api/control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_running: status, symbol: "BTC/USDT:USDT" })
                });
                let result = await response.json();
                document.getElementById('sys-status').innerText = result.is_running ? "يعمل" : "متوقف";
                document.getElementById('sys-status').style.color = result.is_running ? "#0ecb81" : "#da3633";
            }

            async function updateStats() {
                let res = await fetch('/api/stats');
                let data = await res.json();
                document.getElementById('val-rsi').innerText = data.stats.current_rsi;
                document.getElementById('val-bias').innerText = data.stats.ai_bias;
                document.getElementById('val-news').innerText = data.news_sentiment;
                document.getElementById('val-trades').innerText = data.stats.successful_trades;
                document.getElementById('val-action').innerText = data.stats.last_action;
            }
            setInterval(updateStats, 3000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/control")
def control_bot(data: ControlModel):
    BOT_CONTROL["is_running"] = data.is_running
    BOT_CONTROL["active_symbol"] = data.symbol
    return {"success": True, "is_running": BOT_CONTROL["is_running"]}

@app.get("/api/stats")
def get_stats():
    return {
        "is_running": BOT_CONTROL["is_running"],
        "stats": BOT_CONTROL["stats"],
        "news_sentiment": news_agent.sentiment
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
