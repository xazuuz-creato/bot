import os
import sys
import time
import asyncio
import pandas as pd
import ccxt
import aiohttp
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# --- إعدادات التوقيت المحلي لمدينة الرياض ---
RIYADH_TZ = timezone(timedelta(hours=3))

def get_riyadh_time():
    return datetime.now(RIYADH_TZ).strftime('%Y-%m-%d %I:%M:%S %p')

# --- خادم الويب الفوري المستقر لمنع إغلاق Render ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = """
        <!DOCTYPE html>
        <html dir="rtl" lang="ar">
        <head><meta charset="UTF-8"><title>Scalping AI Agent System Running 24/7</title></head>
        <body style="background:#0b0e11; color:#0ecb81; text-align:center; font-family:Arial; padding:50px;">
            <h1>🚀 نظام وكلاء السكالبينغ بالذكاء الاصطناعي يعمل باستقرار تام 24/7 بتوقيت الرياض</h1>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))
    
    def log_message(self, format, *args):
        pass

def run_fast_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# تشغيل خادم الاستقرار في خلفية مستقلة تماماً
server_thread = Thread(target=run_fast_server, daemon=True)
server_thread.start()


class ScalpingAIAgentSystem:
    def __init__(self, symbol='BTC/USDT:USDT'):
        self.symbol = symbol
        self.exchange = self.init_exchange()
        self.ai_trend_bias = "NEUTRAL"
        self.last_ai_check = 0

    def init_exchange(self):
        """تهيئة الاتصال بمنصة OKX باستخدام مفاتيح الاعتماد المباشرة"""
        exchange = ccxt.okx({
            'apiKey': '2bf148cb-c010-49fb-bffc-79f72720dfae',
            'secret': '1FBA3210BF6500BB1A1570EE9EC41A5C',
            'password': 'Aa11223344##',
            'enableRateLimit': True,
        })
        exchange.set_sandbox_mode(True)
        return exchange

    def run_ai_risk_manager_agent(self, df):
        """محاكاة لوكيل الـ AI (مدير المخاطر والاتجاه)"""
        try:
            last_close = df['close'].iloc[-1]
            sma_20 = df['close'].rolling(20).mean().iloc[-1]
            
            if last_close > sma_20:
                return "BULLISH"
            else:
                return "BEARISH"
        except Exception as e:
            print(f"[{get_riyadh_time()}] [-] خطأ في تحليل وكيل الذكاء الاصطناعي: {e}", flush=True, file=sys.stdout)
            return "NEUTRAL"

    def fetch_market_data(self):
        """جلب البيانات اللحظية للشموع (فريم 1 دقيقة للسكالبينغ) بأمان"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe='1m', limit=50)
            if ohlcv and len(ohlcv) > 0:
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                return df
        except Exception as e:
            print(f"[{get_riyadh_time()}] ⚠️ [خطأ جلب البيانات]: {e}", flush=True, file=sys.stdout)
        return None

    async def execute_scalp_strategy(self):
        print(f"[{get_riyadh_time()}] 🚀 [*] بدء تشغيل نظام وكلاء السكالبينغ الموجه للزوج: {self.symbol}", flush=True, file=sys.stdout)
        
        while True:
            try:
                current_time = time.time()
                df = self.fetch_market_data()
                
                if df is None or len(df) < 25:
                    print(f"[{get_riyadh_time()}] 🔄 جاري إعادة محاولة الاتصال وجلب الشموع...", flush=True, file=sys.stdout)
                    await asyncio.sleep(10)
                    continue

                # 1. تحديث رؤية وكيل الذكاء الاصطناعي للاتجاه كل 300 ثانية (5 دقائق)
                if current_time - self.last_ai_check > 300:
                    self.ai_trend_bias = self.run_ai_risk_manager_agent(df)
                    print(f"[{get_riyadh_time()}] [🤖 AI Agent Risk Manager] تحديث الاتجاه العام للسوق: {self.ai_trend_bias}", flush=True, file=sys.stdout)
                    self.last_ai_check = current_time

                # 2. حساب المؤشرات الفنية للسكالبينغ
                close_prices = df['close']
                rsi = self.calculate_rsi(close_prices, window=14)
                current_rsi = rsi.iloc[-1]
                current_price = close_prices.iloc[-1]

                print(f"[{get_riyadh_time()}] [⚡ Scalp Check] السعر: {current_price} | RSI: {current_rsi:.2f} | اتجاه الـ AI: {self.ai_trend_bias}", flush=True, file=sys.stdout)

                # 3. شروط التنفيذ السريع
                if current_rsi < 30 and self.ai_trend_bias == "BULLISH":
                    print(f"[{get_riyadh_time()}] [+] شروط السكالبينغ مكتملة (شراء)... جارٍ إرسال الطلب لـ OKX", flush=True, file=sys.stdout)
                    await asyncio.sleep(10)

                # فترة راحة آمنة لكل دورة لتخفيف الضغط على المعالج ومنع التوقف
                await asyncio.sleep(15)

            except ccxt.NetworkError as ne:
                print(f"[{get_riyadh_time()}] [-] خطأ شبكة: {ne}", flush=True, file=sys.stdout)
                await asyncio.sleep(15)
            except ccxt.ExchangeError as ee:
                print(f"[{get_riyadh_time()}] [-] منصة OKX رفضت الطلب مؤقتاً: {ee}", flush=True, file=sys.stdout)
                await asyncio.sleep(15)
            except Exception as ex:
                print(f"[{get_riyadh_time()}] [-] خطأ غير متوقع في الحلقة: {ex}", flush=True, file=sys.stdout)
                await asyncio.sleep(15)

    def calculate_rsi(self, series, window=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

# --- حلقة الإنعاش والتحقق الذاتي (Self-Ping Keep-Alive) ---
async def self_ping_loop():
    port = int(os.environ.get("PORT", 10000))
    render_url = f"http://127.0.0.1:{port}/"
    while True:
        try:
            await asyncio.sleep(60)  # إرسال إشارة كل دقيقة لمنع خمول المنصة
            async with aiohttp.ClientSession() as session:
                async with session.get(render_url) as resp:
                    pass
        except Exception:
            pass

async def main():
    bot = ScalpingAIAgentSystem(symbol='BTC/USDT:USDT')
    await asyncio.gather(
        self_ping_loop(),
        bot.execute_scalp_strategy()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
