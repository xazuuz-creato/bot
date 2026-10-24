import os
import asyncio
import aiohttp
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

app = FastAPI(title="OKX Scalping AI System")

# قراءة واجهة التطبيق (index.html) وعرضها للزوار وسيرفرات المراقبة
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return "<h1>Error: index.html not found! Please upload index.html</h1>"

# --- حلقة الإنعاش الذاتي (Self-Ping Loop) لمنع خمول وانطفاء سيرفر Render المجاني ---
async def self_ping_loop():
    # الحصول على المنفذ (Port) المخصص من Render أو افتراضي 10000
    port = int(os.environ.get("PORT", 10000))
    render_url = f"http://127.0.0.1:{port}/"
    
    # انتظار بدء تشغيل السيرفر بالكامل لمدة 5 ثوانٍ
    await asyncio.sleep(5)
    
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(render_url) as resp:
                    pass
        except Exception:
            pass
        # إرسال طلب إنعاش ذاتي كل دقيقة (60 ثانية) ليبقى السيرفر نشطاً للأبد
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    # تشغيل حلقة الإنعاش الذاتي في الخلفية بالتزامن مع عمل السيرفر
    asyncio.create_task(self_ping_loop())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
