import json
import os
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from shutil import which

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("OPENSTUDIO_DATA", str(ROOT / "data")))
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"

for folder in (UPLOADS, OUTPUTS):
    folder.mkdir(parents=True, exist_ok=True)

DB = DATA / "studio.sqlite3"
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
ALLOWED = {".png", ".jpg", ".jpeg", ".webp",
           ".mp4", ".mov", ".webm"}

PRESETS = {
    "preview": (640, 360),
    "hd": (1920, 1080),
    "4k": (3840, 2160),
}

app = FastAPI(title="OpenStudio AI", version="0.2-lite")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")),
          name="static")

if os.getenv("SENTRY_DSN"):
    import sentry_sdk
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        traces_sample_rate=0.05,
        send_default_pii=False,
    )


def db_connect():
    connection = sqlite3.connect(DB, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


with db_connect() as db:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            kind TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            status TEXT NOT NULL,
            preset TEXT NOT NULL,
            duration INTEGER NOT NULL,
            error TEXT,
            created_at REAL NOT NULL
        );
    """)
    db.execute(
        "UPDATE jobs SET status='interrupted', "
        "error='Server restarted' "
        "WHERE status IN ('queued','running')"
    )
    db.commit()


def query(sql, params=(), many=False):
    with db_connect() as db:
        result = db.execute(sql, params)
        rows = result.fetchall() if many else result.fetchone()
        return ([dict(x) for x in rows] if many
                else dict(rows) if rows else None)


def execute(sql, params=()):
    with db_connect() as db:
        db.execute(sql, params)
        db.commit()


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class RenderInput(BaseModel):
    project_id: str
    asset_id: str
    preset: str = "preview"
    duration: int = Field(default=5, ge=1, le=60)


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "ffmpeg": bool(which("ffmpeg")),
    }


@app.get("/api/capabilities")
def capabilities():
    return {
        "render": bool(which("ffmpeg")),
        "sentry": bool(os.getenv("SENTRY_DSN")),
        "ai_video": False,
        "mcp": False,
        "ai_upscale": False,
        "note": "4K uses standard scaling, not AI enhancement."
    }


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectInput):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Project name is empty")

    item = {
        "id": uuid.uuid4().hex,
        "name": name,
        "created_at": time.time(),
    }

    execute(
        "INSERT INTO projects VALUES (?,?,?)",
        (item["id"], item["name"], item["created_at"]),
    )
    return item


@app.get("/api/projects")
def list_projects():
    return query(
        "SELECT * FROM projects ORDER BY created_at DESC",
        many=True,
    )


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = query(
        "SELECT * FROM projects WHERE id=?",
        (project_id,),
    )
    if not project:
        raise HTTPException(404, "Project not found")

    project["assets"] = query(
        "SELECT id,project_id,filename,kind FROM assets "
        "WHERE project_id=?",
        (project_id,),
        many=True,
    )
    project["jobs"] = query(
        "SELECT * FROM jobs WHERE project_id=? "
        "ORDER BY created_at DESC",
        (project_id,),
        many=True,
    )
    return project


@app.post("/api/assets", status_code=201)
async def upload(
    project_id: str = Form(...),
    file: UploadFile = File(...),
):
    if not query(
        "SELECT id FROM projects WHERE id=?",
        (project_id,),
    ):
        raise HTTPException(404, "Project not found")

    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED:
        raise HTTPException(415, "Unsupported file type")

    asset_id = uuid.uuid4().hex
    target = UPLOADS / (asset_id + suffix)
    total = 0

    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, "File too large")
                output.write(chunk)

        if total == 0:
            raise HTTPException(422, "Empty file")

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=codec_type",
                "-of", "json", str(target),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if probe.returncode != 0:
            raise HTTPException(422, "Invalid media")

        streams = json.loads(probe.stdout).get("streams", [])
        if not any(s.get("codec_type") == "video" for s in streams):
            raise HTTPException(422, "No visual stream")

        kind = "image" if suffix in {
            ".png", ".jpg", ".jpeg", ".webp"
        } else "video"

        execute(
            "INSERT INTO assets VALUES (?,?,?,?,?)",
            (asset_id, project_id, filename[:200],
             str(target), kind),
        )

        return {
            "id": asset_id,
            "project_id": project_id,
            "filename": filename,
            "kind": kind,
        }

    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def render_video(job_id: str):
    job = query("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        return

    asset = query(
        "SELECT * FROM assets WHERE id=? AND project_id=?",
        (job["asset_id"], job["project_id"]),
    )

    if not asset:
        execute(
            "UPDATE jobs SET status=?,error=? WHERE id=?",
            ("failed", "Asset missing", job_id),
        )
        return

    execute(
        "UPDATE jobs SET status='running' WHERE id=?",
        (job_id,),
    )

    try:
        width, height = PRESETS[job["preset"]]
        output = OUTPUTS / f"{job_id}.mp4"

        filters = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=decrease:"
            "flags=lanczos,"
            f"pad={width}:{height}:"
            "(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,format=yuv420p"
        )

        cmd = [
            "ffmpeg", "-nostdin", "-hide_banner",
            "-loglevel", "error", "-y",
        ]

        if asset["kind"] == "image":
            cmd += [
                "-loop", "1", "-framerate", "24",
                "-i", asset["path"],
                "-t", str(job["duration"]),
            ]
        else:
            cmd += [
                "-i", asset["path"],
                "-t", str(job["duration"]),
            ]

        cmd += [
            "-vf", filters,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-movflags", "+faststart",
        ]

        if asset["kind"] == "image":
            cmd += ["-an"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "128k"]

        cmd.append(str(output))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(120, job["duration"] * 30),
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr[-300:])

        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError("Output missing")

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json", str(output),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )

        info = json.loads(probe.stdout)["streams"][0]
        if (info["width"], info["height"]) != (width, height):
            raise RuntimeError("Unexpected output resolution")

        execute(
            "UPDATE jobs SET status='completed',error=NULL "
            "WHERE id=?",
            (job_id,),
        )

    except Exception as exc:
        execute(
            "UPDATE jobs SET status='failed',error=? "
            "WHERE id=?",
            (str(exc)[:300], job_id),
        )
        if os.getenv("SENTRY_DSN"):
            import sentry_sdk
            sentry_sdk.capture_exception(exc)


@app.post("/api/jobs", status_code=202)
def create_job(body: RenderInput, background: BackgroundTasks):
    if body.preset not in PRESETS:
        raise HTTPException(422, "Invalid preset")

    asset = query(
        "SELECT id FROM assets WHERE id=? AND project_id=?",
        (body.asset_id, body.project_id),
    )
    if not asset:
        raise HTTPException(404, "Asset not found")

    job_id = uuid.uuid4().hex

    execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
        (
            job_id, body.project_id, body.asset_id,
            "queued", body.preset, body.duration,
            None, time.time(),
        ),
    )

    background.add_task(render_video, job_id)

    return {"id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = query("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        raise HTTPException(404, "Job not found")

    job["download_url"] = (
        f"/api/jobs/{job_id}/download"
        if job["status"] == "completed" else None
    )
    return job


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    job = query("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job or job["status"] != "completed":
        raise HTTPException(404, "Output not ready")

    output = OUTPUTS / f"{job_id}.mp4"
    if not output.is_file():
        raise HTTPException(404, "Output missing")

    return FileResponse(
        output,
        media_type="video/mp4",
        filename=f"openstudio-{job_id[:8]}.mp4",
    )
