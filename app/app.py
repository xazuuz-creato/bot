
import os
import json
import time
import uuid
import sqlite3
import hashlib
import hmac
import secrets
import subprocess
import shutil
import re
import textwrap
import asyncio

from pathlib import Path
from contextlib import contextmanager
from xml.etree import ElementTree as ET
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw, ImageFont
from fastapi import (
    FastAPI,
    HTTPException,
    Header,
    BackgroundTasks,
)
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field


# ==========================================
# CONFIGURATION
# ==========================================

BASE = Path(
    os.getenv("DATA_DIR", "./data")
).resolve()

BASE.mkdir(parents=True, exist_ok=True)

DB = BASE / "studio.db"
OUTPUT = BASE / "outputs"
OUTPUT.mkdir(exist_ok=True)

OLLAMA = os.getenv(
    "OLLAMA_URL", ""
).rstrip("/")

MODEL = os.getenv(
    "OLLAMA_MODEL", "qwen2.5:7b"
)

SENTRY = os.getenv("SENTRY_DSN", "")

if SENTRY:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY,
        traces_sample_rate=0.05,
        send_default_pii=False,
    )

app = FastAPI(
    title="OpenStudio AI",
    version="0.4.0-mvp",
)


# ==========================================
# DATABASE
# ==========================================

@contextmanager
def db():
    connection = sqlite3.connect(
        DB,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


with db() as connection:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        passhash TEXT
    );

    CREATE TABLE IF NOT EXISTS sessions (
        tokenhash TEXT PRIMARY KEY,
        user_id TEXT
    );

    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        topic TEXT,
        status TEXT,
        stage TEXT,
        plan TEXT,
        error TEXT,
        created REAL
    );
    """)

    connection.execute("""
        UPDATE jobs
        SET status = 'interrupted'
        WHERE status IN ('queued', 'running')
    """)


# ==========================================
# MODELS
# ==========================================

class Credentials(BaseModel):
    email: str
    password: str = Field(
        min_length=8,
        max_length=128,
    )


class VideoRequest(BaseModel):
    topic: str = Field(
        min_length=5,
        max_length=500,
    )

    duration: int = Field(
        default=60,
        ge=10,
        le=120,
    )

    news: bool = True


# ==========================================
# AUTHENTICATION
# ==========================================

def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)

    result = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        240000,
    )

    return salt.hex() + ":" + result.hex()


def verify_password(password, stored):
    try:
        salt, expected = stored.split(":")

        actual = password_hash(
            password,
            bytes.fromhex(salt),
        ).split(":")[1]

        return hmac.compare_digest(
            actual,
            expected,
        )

    except Exception:
        return False


def current_user(authorization):
    token = (
        authorization or ""
    ).removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            401,
            "يلزم تسجيل الدخول",
        )

    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    with db() as connection:
        row = connection.execute(
            """
            SELECT user_id
            FROM sessions
            WHERE tokenhash = ?
            """,
            (token_hash,),
        ).fetchone()

    if not row:
        raise HTTPException(
            401,
            "جلسة غير صالحة",
        )

    return row["user_id"]


@app.post("/api/register")
def register(credentials: Credentials):
    email = credentials.email.strip().lower()

    if not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        email,
    ):
        raise HTTPException(
            422,
            "البريد الإلكتروني غير صالح",
        )

    try:
        with db() as connection:
            connection.execute(
                """
                INSERT INTO users
                VALUES (?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    email,
                    password_hash(
                        credentials.password
                    ),
                ),
            )

    except sqlite3.IntegrityError:
        raise HTTPException(
            409,
            "البريد مسجل بالفعل",
        )

    return {"ok": True}


@app.post("/api/login")
def login(credentials: Credentials):
    email = credentials.email.strip().lower()

    with db() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

    if not row or not verify_password(
        credentials.password,
        row["passhash"],
    ):
        raise HTTPException(
            401,
            "بيانات الدخول غير صحيحة",
        )

    token = secrets.token_urlsafe(40)

    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    with db() as connection:
        connection.execute(
            """
            INSERT INTO sessions
            VALUES (?, ?)
            """,
            (
                token_hash,
                row["id"],
            ),
        )

    return {"token": token}


# ==========================================
# HEALTH AND CAPABILITIES
# ==========================================

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": app.version,
        "ffmpeg": bool(
            shutil.which("ffmpeg")
        ),
        "ollama_configured": bool(OLLAMA),
        "sentry_configured": bool(SENTRY),
        "ai_video_generation": False,
        "ai_upscaling": False,
        "mcp_connected": False,
    }


# ==========================================
# NEWS RESEARCH
# ==========================================

async def search_news(topic):
    url = (
        "https://news.google.com/rss/search?q="
        + quote(topic)
        + "&hl=ar&gl=SA&ceid=SA:ar"
    )

    try:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        root = ET.fromstring(
            response.text
        )

        items = []

        for item in root.findall(".//item")[:6]:
            items.append({
                "title": item.findtext(
                    "title", ""
                )[:220],
                "url": item.findtext(
                    "link", ""
                ),
                "published": item.findtext(
                    "pubDate", ""
                ),
            })

        return items

    except Exception:
        return []


# ==========================================
# AI SCRIPT WRITER
# ==========================================

async def write_script(
    topic,
    duration,
    use_news,
):
    sources = (
        await search_news(topic)
        if use_news
        else []
    )

    if OLLAMA:
        prompt = f"""
أنت مخرج موشن جرافيك إخباري محترف.

الموضوع:
{topic}

مدة الفيديو:
{duration} ثانية

عناوين الأخبار المتاحة:
{json.dumps(sources, ensure_ascii=False)}

المطلوب:

1. إعداد سيناريو عربي جذاب.
2. تقسيم الفيديو إلى 6 مشاهد.
3. كتابة عنوان لكل مشهد.
4. كتابة نص التعليق الصوتي.
5. كتابة برومبت تفصيلي للصورة.
6. مراعاة الموشن جرافيك.
7. استخدام لغة إخبارية احترافية.
8. عدم اختراع أرقام أو تصريحات.
9. عدم اعتبار عناوين البحث حقائق مؤكدة.

أرجع JSON فقط بهذه البنية:

{{
  "scenes": [
    {{
      "title": "عنوان المشهد",
      "narration": "نص التعليق الصوتي",
      "visual_prompt": "English visual prompt"
    }}
  ]
}}
"""

        try:
            async with httpx.AsyncClient(
                timeout=100
            ) as client:
                response = await client.post(
                    OLLAMA + "/api/generate",
                    json={
                        "model": MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )

                response.raise_for_status()

            result = json.loads(
                response.json()["response"]
            )

            scenes = result.get(
                "scenes", []
            )

            if (
                isinstance(scenes, list)
                and len(scenes) >= 2
            ):
                cleaned = []

                for scene in scenes[:10]:
                    if not isinstance(
                        scene, dict
                    ):
                        continue

                    cleaned.append({
                        "title": str(
                            scene.get(
                                "title", "مشهد"
                            )
                        )[:100],
                        "narration": str(
                            scene.get(
                                "narration", ""
                            )
                        )[:700],
                        "visual_prompt": str(
                            scene.get(
                                "visual_prompt", ""
                            )
                        )[:500],
                    })

                if len(cleaned) >= 2:
                    return (
                        cleaned,
                        sources,
                        "ollama",
                    )

        except Exception:
            pass

    # Fallback when AI is unavailable
    titles = [
        source["title"]
        for source in sources[:5]
    ]

    if not titles:
        titles = [
            f"مقدمة عن {topic}",
            "الخلفية والسياق",
            "أبرز الجوانب",
            "التحليل",
            "ما الذي ينبغي متابعته؟",
            "الخلاصة",
        ]

    scenes = []

    for index in range(6):
        title = titles[
            index % len(titles)
        ]

        scenes.append({
            "title": title,
            "narration": (
                f"المشهد {index + 1}: "
                f"{title}. "
                "هذه مسودة أولية، "
                "ويجب مراجعة المعلومات "
                "قبل النشر."
            ),
            "visual_prompt": (
                "Professional Arabic news "
                "motion graphics, "
                f"{topic}, {title}, "
                "cinematic editorial style, "
                "modern lighting, "
                "16:9 composition, "
                "no embedded text"
            ),
        })

    return scenes, sources, "template"


# ==========================================
# VISUAL DESIGN
# ==========================================

def load_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans.ttf",

        "/usr/share/fonts/truetype/noto/"
        "NotoSansArabic-Regular.ttf",

        "/System/Library/Fonts/Supplemental/"
        "Arial Unicode.ttf",
    ]

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(
                path,
                size,
            )

    return ImageFont.load_default()


def create_slide(
    path,
    title,
    index,
    total,
):
    image = Image.new(
        "RGB",
        (1280, 720),
        (10, 16, 35),
    )

    draw = ImageDraw.Draw(image)

    # Gradient background
    for y in range(720):
        draw.line(
            (0, y, 1280, y),
            fill=(
                10 + y // 45,
                16 + y // 30,
                35 + y // 15,
            ),
        )

    draw.rounded_rectangle(
        (65, 65, 1215, 655),
        radius=34,
        outline=(86, 109, 210),
        width=4,
    )

    draw.rectangle(
        (65, 65, 78, 655),
        fill=(105, 105, 245),
    )

    draw.text(
        (115, 110),
        "OPENSTUDIO AI | NEWS MOTION",
        font=load_font(27),
        fill=(164, 175, 255),
    )

    lines = textwrap.wrap(
        title,
        width=34,
    )[:4]

    for i, line in enumerate(lines):
        position = (
            115,
            250 + i * 68,
        )

        try:
            draw.text(
                position,
                line,
                font=load_font(45),
                fill="white",
                direction="rtl",
            )

        except (ValueError, KeyError):
            draw.text(
                position,
                line,
                font=load_font(45),
                fill="white",
            )

    draw.text(
        (115, 595),
        f"SCENE {index + 1:02d} "
        f"/ {total:02d}",
        font=load_font(26),
        fill=(170, 187, 220),
    )

    image.save(path)


# ==========================================
# JOB MANAGEMENT
# ==========================================

def update_job(job_id, **fields):
    allowed = {
        "status",
        "stage",
        "plan",
        "error",
    }

    with db() as connection:
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(
                    "Invalid job field"
                )

            connection.execute(
                f"""
                UPDATE jobs
                SET {key} = ?
                WHERE id = ?
                """,
                (value, job_id),
            )


def produce_video(
    job_id,
    topic,
    duration,
    use_news,
):
    try:
        update_job(
            job_id,
            status="running",
            stage="research",
        )

        scenes, sources, writer = (
            asyncio.run(
                write_script(
                    topic,
                    duration,
                    use_news,
                )
            )
        )

        folder = OUTPUT / job_id
        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        plan = {
            "topic": topic,
            "duration": duration,
            "scenes": scenes,
            "sources": sources,
            "writer": writer,
            "verification_required": True,
        }

        (folder / "plan.json").write_text(
            json.dumps(
                plan,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        update_job(
            job_id,
            stage="slides",
            plan=json.dumps(
                plan,
                ensure_ascii=False,
            ),
        )

        for index, scene in enumerate(scenes):
            create_slide(
                folder / f"{index:03}.png",
                scene["title"],
                index,
                len(scenes),
            )

        if not shutil.which("ffmpeg"):
            raise RuntimeError(
                "FFmpeg غير مثبت"
            )

        update_job(
            job_id,
            stage="render",
        )

        seconds_per_scene = (
            duration / len(scenes)
        )

        segments = []

        for index, scene in enumerate(scenes):
            image_path = (
                folder / f"{index:03}.png"
            )

            video_path = (
                folder / f"{index:03}.mp4"
            )

            command = [
                "ffmpeg",
                "-nostdin",
                "-loglevel", "error",
                "-y",
                "-loop", "1",
                "-framerate", "25",
                "-i", str(image_path),
                "-t", str(seconds_per_scene),
                "-vf",
                "scale=1280:720,"
                "format=yuv420p",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                str(video_path),
            ]

            subprocess.run(
                command,
                check=True,
                timeout=180,
            )

            segments.append(video_path)

        concat_file = (
            folder / "concat.txt"
        )

        concat_file.write_text(
            "".join(
                "file '"
                + str(path.resolve())
                .replace("'", "'\\''")
                + "'\n"
                for path in segments
            ),
            encoding="utf-8",
        )

        final_path = (
            folder / "final.mp4"
        )

        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel", "error",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                "-movflags", "+faststart",
                str(final_path),
            ],
            check=True,
            timeout=180,
        )

        if not final_path.exists():
            raise RuntimeError(
                "لم يتم إنشاء الفيديو"
            )

        update_job(
            job_id,
            status="completed",
            stage="done",
        )

    except Exception as error:
        update_job(
            job_id,
            status="failed",
            stage="error",
            error=str(error)[:400],
        )

        if SENTRY:
            import sentry_sdk
            sentry_sdk.capture_exception(
                error
            )


# ==========================================
# VIDEO API
# ==========================================

@app.post(
    "/api/jobs",
    status_code=202,
)
def create_job(
    request: VideoRequest,
    background: BackgroundTasks,
    authorization: str | None = Header(None),
):
    user_id = current_user(
        authorization
    )

    job_id = uuid.uuid4().hex

    with db() as connection:
        connection.execute(
            """
            INSERT INTO jobs
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                request.topic,
                "queued",
                "queued",
                None,
                None,
                time.time(),
            ),
        )

    background.add_task(
        produce_video,
        job_id,
        request.topic,
        request.duration,
        request.news,
    )

    return {
        "id": job_id,
        "status": "queued",
    }


@app.get("/api/jobs")
def list_jobs(
    authorization: str | None = Header(None),
):
    user_id = current_user(
        authorization
    )

    with db() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                topic,
                status,
                stage,
                error,
                created
            FROM jobs
            WHERE user_id = ?
            ORDER BY created DESC
            """,
            (user_id,),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


@app.get("/api/jobs/{job_id}")
def get_job(
    job_id: str,
    authorization: str | None = Header(None),
):
    user_id = current_user(
        authorization
    )

    with db() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM jobs
            WHERE id = ?
            AND user_id = ?
            """,
            (
                job_id,
                user_id,
            ),
        ).fetchone()

    if not row:
        raise HTTPException(
            404,
            "المهمة غير موجودة",
        )

    result = dict(row)

    if result["plan"]:
        result["plan"] = json.loads(
            result["plan"]
        )

    return result


@app.get("/api/jobs/{job_id}/video")
def download_video(
    job_id: str,
    token: str,
):
    # Development-only download authentication.
    # For production use secure cookies or
    # short-lived signed download URLs.
    user_id = current_user(
        "Bearer " + token
    )

    with db() as connection:
        row = connection.execute(
            """
            SELECT status
            FROM jobs
            WHERE id = ?
            AND user_id = ?
            """,
            (
                job_id,
                user_id,
            ),
        ).fetchone()

    if (
        not row
        or row["status"] != "completed"
    ):
        raise HTTPException(
            404,
            "الفيديو غير جاهز",
        )

    output_file = (
        OUTPUT / job_id / "final.mp4"
    )

    if not output_file.is_file():
        raise HTTPException(
            404,
            "ملف الفيديو غير موجود",
        )

    return FileResponse(
        output_file,
        media_type="video/mp4",
        filename="openstudio.mp4",
    )


# ==========================================
# WEB INTERFACE
# ==========================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
def homepage():
    return HTML


HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>OpenStudio AI</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #0b1020;
    color: #e8edff;
    font-family: system-ui, Arial, sans-serif;
}

header {
    background: #151d37;
    padding: 24px;
    border-bottom: 1px solid #334265;
}

header h1 {
    margin: 0;
    color: #b7c6ff;
}

main {
    max-width: 1050px;
    margin: auto;
    padding: 24px;
}

.card {
    background: #19223b;
    border: 1px solid #334265;
    border-radius: 16px;
    padding: 22px;
    margin: 16px 0;
}

.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}

input,
textarea,
button {
    font: inherit;
    padding: 12px;
    border-radius: 9px;
    margin: 5px 0;
}

input,
textarea {
    background: #0c1429;
    color: white;
    border: 1px solid #465474;
    width: 100%;
}

button {
    background: #686cf2;
    color: white;
    border: none;
    cursor: pointer;
}

button:hover {
    background: #5056d7;
}

.muted {
    color: #9baccb;
}

a {
    color: #b7c6ff;
}

#msg {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.job {
    background: #111a31;
    border-radius: 12px;
    padding: 15px;
    margin: 10px 0;
}

@media(max-width:700px) {
    .grid {
        grid-template-columns: 1fr;
    }

    main {
        padding: 12px;
    }
}
</style>
</head>

<body>

<header>
    <h1>🎬 OpenStudio AI</h1>
    <p>استوديو تصميم الفيديو والموشن جرافيك</p>
</header>

<main>

<div class="card">
    <h2>حساب المستخدم</h2>

    <div class="grid">
        <input
            id="email"
            type="email"
            placeholder="البريد الإلكتروني"
        >

        <input
            id="pass"
            type="password"
            placeholder="كلمة المرور"
        >
    </div>

    <button onclick="auth('register')">
        إنشاء حساب
    </button>

    <button onclick="auth('login')">
        تسجيل الدخول
    </button>
</div>

<div class="card">
    <h2>مساعد التصميم الذكي</h2>

    <p class="muted">
        اكتب الموضوع الذي تريد إنتاج فيديو عنه.
    </p>

    <textarea
        id="topic"
        rows="5"
        placeholder="صمم فيديو موشن جرافيك إخباري لمدة دقيقة عن أحدث تطورات الذكاء الاصطناعي، بعناوين جذابة ومشاهد احترافية."
    ></textarea>

    <label>مدة الفيديو بالثواني</label>

    <input
        id="duration"
        type="number"
        value="60"
        min="10"
        max="120"
    >

    <p>
        <label>
            <input
                id="news"
                type="checkbox"
                checked
                style="width:auto"
            >
            البحث عن عناوين أخبار حديثة
        </label>
    </p>

    <button onclick="createVideo()">
        ابدأ تصميم الفيديو
    </button>

    <p class="muted">
        عند تفعيل Ollama، يُستخدم لكتابة
        السيناريو والبرومبتات.
        الإصدار الحالي ينتج شرائح فيديو،
        وليس صورًا مولدة بالذكاء الاصطناعي.
    </p>
</div>

<div class="card">
    <h2>مشاريع الفيديو</h2>

    <button onclick="refreshJobs()">
        تحديث المهام
    </button>

    <div id="jobs"></div>
</div>

<div class="card">
    <h2>سجل التطبيق</h2>

    <div id="msg" class="muted">
        التطبيق جاهز.
    </div>
</div>

</main>

<script>
let token = sessionStorage.getItem("token") || "";

async function api(path, options = {}) {
    options.headers = {
        ...(options.headers || {}),
        ...(token
            ? {Authorization: "Bearer " + token}
            : {})
    };

    const response = await fetch(path, options);

    const data = await response.json();

    if (!response.ok) {
        throw new Error(
            JSON.stringify(data)
        );
    }

    return data;
}

function message(text) {
    document.getElementById("msg").textContent = text;
}

async function auth(kind) {
    try {
        const result = await api(
            "/api/" + kind,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    email: document.getElementById("email").value,
                    password: document.getElementById("pass").value
                })
            }
        );

        if (result.token) {
            token = result.token;

            sessionStorage.setItem(
                "token",
                token
            );

            message("تم تسجيل الدخول بنجاح");

            await refreshJobs();
        } else {
            message(
                "تم إنشاء الحساب. سجل الدخول الآن."
            );
        }

    } catch (error) {
        message(error.message);
    }
}

async function createVideo() {
    try {
        const result = await api(
            "/api/jobs",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    topic: document.getElementById("topic").value,
                    duration: Number(
                        document.getElementById("duration").value
                    ),
                    news: document.getElementById("news").checked
                })
            }
        );

        message(
            "بدأ إنتاج الفيديو. رقم المهمة: " +
            result.id
        );

        await refreshJobs();

    } catch (error) {
        message(error.message);
    }
}

async function refreshJobs() {
    if (!token) return;

    try {
        const jobs = await api("/api/jobs");

        const container = document.getElementById("jobs");

        container.replaceChildren();

        for (const job of jobs) {
            const box = document.createElement("div");

            box.className = "job";

            const title = document.createElement("p");

            title.textContent =
                job.topic + " — " +
                job.status + " / " +
                job.stage;

            box.append(title);

            if (job.error) {
                const error = document.createElement("p");
                error.textContent = job.error;
                box.append(error);
            }

            if (job.status === "completed") {
                const link = document.createElement("a");

                link.href =
                    "/api/jobs/" +
                    encodeURIComponent(job.id) +
                    "/video?token=" +
                    encodeURIComponent(token);

                link.textContent = "تنزيل الفيديو MP4";

                box.append(link);
            }

            const planButton = document.createElement("button");

            planButton.textContent = "عرض السيناريو والبرومبتات";

            planButton.onclick = async () => {
                const details = await api(
                    "/api/jobs/" + job.id
                );

                message(
                    JSON.stringify(
                        details.plan,
                        null,
                        2
                    )
                );
            };

            box.append(planButton);
            container.append(box);
        }

    } catch (error) {
        message(error.message);
    }
}

setInterval(refreshJobs, 6000);

refreshJobs();
</script>

</body>
</html>
"""
