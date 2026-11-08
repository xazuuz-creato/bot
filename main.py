import os
import json
import asyncio
import re
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="Smart AI Open-Source Router Engine")

# السماح لجميع الأصول بالاتصال
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مفتاح OpenRouter من متغيرات البيئة على Render أو المفتاح الافتراضي
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# مصفوفة توجيه الأسئلة إلى أقوى النماذج المفتوحة
ROUTING_MATRIX = {
    "MATH": {
        "model": "deepseek/deepseek-r1",
        "name": "DeepSeek-R1 (المحرك الرياضي)",
        "badge": "🧮 رياضيات واستدلال"
    },
    "CODING": {
        "model": "zhipuai/glm-5.3", # أو qwen/qwen-2.5-coder-32b-instruct
        "name": "GLM-5.3 / Qwen Coder",
        "badge": "💻 برمجة وأمن سيبراني"
    },
    "AGENTIC": {
        "model": "moonshotai/kimi-k3",
        "name": "Kimi K3 Ultra",
        "badge": "🧠 استدلال معقد وأنظمة"
    },
    "GENERAL": {
        "model": "meta-llama/llama-3.3-70b-instruct",
        "name": "Llama 3.3 70B",
        "badge": "🌐 أسئلة عامة ولغات"
    }
}

def classify_prompt(prompt: str) -> dict:
    """خوارزمية ذكية لتحليل السؤال وتحديد التصنيف والنموذج المناسب"""
    p = prompt.lower()
    if re.search(r'(\d+|احسب|معادلة|رياضيات|تفاضل|تكامل|احتمال|برهان|اثبت|math|solve|equation|integral|matrix)', p):
        return ROUTING_MATRIX["MATH"]
    elif re.search(r'(كود|برمجة|دالة|ثغرة|python|javascript|html|css|sql|function|bug|api|script|cyber|payload|fix|refactor)', p):
        return ROUTING_MATRIX["CODING"]
    elif re.search(r'(حلل|خطة|مشروع|وكيل|تقرير|architecture|agent|system|strategy|deep)', p):
        return ROUTING_MATRIX["AGENTIC"]
    return ROUTING_MATRIX["GENERAL"]

@app.get("/", response_class=HTMLResponse)
async def get_index():
    """تقديم الواجهة الأمامية المعدلة بنفس التصميم المطلوب مع دعم التدفّق اللحظي"""
    html_content = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>واجهة الذكاء الاصطناعي الذكية - Render Hosted</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: #212121; color: #ececf1; display: flex; height: 100vh; flex-direction: column; }
        .chat-container { display: flex; flex-direction: column; width: 100%; max-width: 900px; margin: 0 auto; height: 100%; }
        .messages-box { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 20px; }
        .message { display: flex; gap: 15px; padding: 15px; border-radius: 8px; max-width: 90%; }
        .user-message { background-color: #2f2f2f; align-self: flex-end; border-bottom-right-radius: 2px; }
        .bot-message { background-color: #1e1e1e; border: 1px solid #333; align-self: flex-start; width: 100%; border-radius: 12px; }
        .avatar { width: 32px; height: 32px; border-radius: 50%; background-color: #10a37f; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 13px; flex-shrink: 0; color: #fff; }
        .user-message .avatar { background-color: #5436da; }
        .text-content { line-height: 1.6; font-size: 15px; width: 100%; overflow-x: auto; }
        .input-area { padding: 20px; background-color: #212121; }
        .input-wrapper { display: flex; background-color: #2f2f2f; border: 1px solid #4f4f4f; border-radius: 12px; padding: 10px 15px; align-items: center; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        textarea { flex: 1; background: transparent; border: none; color: #fff; resize: none; outline: none; font-size: 16px; height: 26px; max-height: 200px; }
        .send-btn { background-color: #676767; color: #212121; border: none; width: 34px; height: 34px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s; margin-right: 10px; font-weight: bold; }
        textarea:not(:placeholder-shown) + .send-btn { background-color: #fff; color: #000; }
        .model-tag { display: inline-flex; items-center: center; gap: 6px; background: #2a2a2a; border: 1px solid #444; padding: 3px 8px; border-radius: 6px; font-size: 12px; color: #10a37f; margin-bottom: 8px; font-weight: bold; }
        pre { background: #0d1117; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 10px 0; }
        code { font-family: monospace; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="messages-box" id="messagesBox">
            <div class="message bot-message">
                <div class="avatar"><i class="fa-solid fa-robot"></i></div>
                <div class="text-content">
                    <div class="model-tag"><i class="fa-solid fa-bolt"></i> خادم Render المحسّن</div>
                    <p>مرحباً بك! السيرفر يعمل الآن بتقنية FastAPI + Async SSE Streaming. اطرح أي سؤال وسيتم توجيهه لحظياً لأقوى نموذج محدد.</p>
                </div>
            </div>
        </div>

        <div class="input-area">
            <div class="input-wrapper">
                <textarea id="userInput" placeholder="أرسل رسالة إلى الذكاء الاصطناعي..."></textarea>
                <button class="send-btn" id="sendBtn" onclick="sendMessage()">⬆</button>
            </div>
        </div>
    </div>

    <script>
        const messagesBox = document.getElementById('messagesBox');
        const userInput = document.getElementById('userInput');

        async function sendMessage() {
            const text = userInput.value.trim();
            if (text === '') return;

            appendUserMessage(text);
            userInput.value = '';

            const botElement = createBotMessageElement();
            const textDiv = botElement.querySelector('.text-div');
            const modelTag = botElement.querySelector('.model-tag');

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let fullText = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\\n');

                    for (const line of lines) {
                        if (line.startsWith("data: ")) {
                            try {
                                const payload = JSON.parse(line.replace("data: ", ""));
                                if (payload.info) {
                                    modelTag.innerHTML = `<i class="fa-solid fa-microchip"></i> ${payload.info.name} | ${payload.info.badge}`;
                                }
                                if (payload.token) {
                                    fullText += payload.token;
                                    textDiv.innerHTML = marked.parse(fullText);
                                    hljs.highlightAll();
                                    messagesBox.scrollTop = messagesBox.scrollHeight;
                                }
                            } catch (e) {}
                        }
                    }
                }
            } catch (err) {
                textDiv.innerText = "حدث خطأ في الاتصال بالخادم: " + err.message;
            }
        }

        function appendUserMessage(text) {
            const div = document.createElement('div');
            div.className = 'message user-message';
            div.innerHTML = `<div class="avatar">أنت</div><div class="text-content">${text}</div>`;
            messagesBox.appendChild(div);
            messagesBox.scrollTop = messagesBox.scrollHeight;
        }

        function createBotMessageElement() {
            const div = document.createElement('div');
            div.className = 'message bot-message';
            div.innerHTML = `
                <div class="avatar"><i class="fa-solid fa-brain"></i></div>
                <div class="text-content">
                    <div class="model-tag"><i class="fa-solid fa-spinner fa-spin"></i> جاري التصنيف والتوجيه...</div>
                    <div class="text-div"></div>
                </div>
            `;
            messagesBox.appendChild(div);
            messagesBox.scrollTop = messagesBox.scrollHeight;
            return div;
        }

        userInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """مقبض API الذي يحلل السؤال ويرسله بنمط Async Streaming"""
    data = await request.json()
    prompt = data.get("prompt", "")
    
    # 1. تحليل وتحديد النموذج المستهدف
    route_info = classify_prompt(prompt)
    api_key = OPENROUTER_API_KEY

    async def generate_stream():
        # إرسال بيانات النموذج المختار أولاً للواجهة
        yield f"data: {json.dumps({'info': route_info})}\n\n"

        if not api_key:
            # رد محاكاة نفاث إذا لم يتم إضافة المفتاح على السيرفر
            simulated_text = f"مرحباً! تم توجيه طلبك بنجاح إلى نموذج **{route_info['name']}**.\n\nلمعالجة الاستجابات الحية من النماذج السحابية، يرجى إضافة متغير البيئة `OPENROUTER_API_KEY` على خادم Render."
            for token in simulated_text.split(" "):
                yield f"data: {json.dumps({'token': token + ' '})}\n\n"
                await asyncio.sleep(0.04)
            return

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://render.com",
            "X-Title": "Fast API Render Router"
        }

        payload = {
            "model": route_info["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": True
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream("POST", "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line.replace("data: ", "").strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                json_data = json.loads(data_str)
                                token = json_data["choices"][0]["delta"].get("content", "")
                                if token:
                                    yield f"data: {json.dumps({'token': token})}\n\n"
                            except Exception:
                                pass
            except Exception as e:
                yield f"data: {json.dumps({'token': f'خطأ أثناء الاتصال بالنموذج: {str(e)}'})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")
