import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import storage
from .config import settings
from .db import init_db, pool
from .worker import worker_loop

ALLOWED_EXT = {".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a"}  # Gnani's supported formats
LANGUAGES = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN",
             "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    await init_db()
    worker_task = asyncio.create_task(worker_loop())  # runs in the background
    yield
    worker_task.cancel()
    await pool.close()


app = FastAPI(title="Audio Notes API", lifespan=lifespan)

# Lets the Next.js site (a different origin) call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    language_code: str = "en-IN"


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/uploads", status_code=201)
async def create_upload(body: CreateUploadRequest):
    """Step 1: validate, create the DB row, hand back a signed upload URL."""
    ext = PurePosixPath(body.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXT)}")
    if body.language_code not in LANGUAGES:
        raise HTTPException(400, f"Unsupported language. Allowed: {sorted(LANGUAGES)}")
    if body.size_bytes > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large. Max is {settings.max_upload_mb} MB.")

    upload_id = uuid.uuid4()
    key = f"uploads/{upload_id}{ext}"  # path inside the bucket

    async with pool.connection() as conn:
        await conn.execute(
            """INSERT INTO uploads
               (id, filename, content_type, size_bytes, storage_key, language_code)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (upload_id, body.filename, body.content_type,
             body.size_bytes, key, body.language_code),
        )

    return {
        "id": upload_id,
        "upload_url": storage.presign_put(key, body.content_type),
        "content_type": body.content_type,  # browser must send this exact header
    }


@app.post("/uploads/{upload_id}/complete")
async def complete_upload(upload_id: uuid.UUID):
    """Step 3: confirm the file reached the bucket, then queue the background job."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM uploads WHERE id = %s", (upload_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(404, "Upload not found.")
    if row["status"] != "uploading":
        return row  # already completed: safe to call twice

    try:
        head = await asyncio.to_thread(storage.head_object, row["storage_key"])
    except Exception:
        raise HTTPException(502, "Could not reach file storage. Please try again.")
    if head is None:
        raise HTTPException(400, "The file never arrived in storage. Please upload again.")

    real_size = head["ContentLength"]
    if real_size <= 0 or real_size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, "Uploaded file is empty or too large.")

    # Both statements below commit together or not at all.
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE uploads SET status = 'queued', size_bytes = %s, updated_at = now() WHERE id = %s",
            (real_size, upload_id),
        )
        await conn.execute(
            "INSERT INTO jobs (upload_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (upload_id,),
        )
    return {"id": upload_id, "status": "queued"}


@app.get("/uploads")
async def list_uploads():
    """Past uploads, newest first."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT id, filename, status, language_code, size_bytes,
                      duration_seconds, created_at
               FROM uploads ORDER BY created_at DESC LIMIT 50"""
        )
        return await cur.fetchall()


@app.get("/uploads/{upload_id}")
async def get_upload(upload_id: uuid.UUID):
    """Everything about one upload: status, progress, transcript, summary, error."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM uploads WHERE id = %s", (upload_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(404, "Upload not found.")
    return row