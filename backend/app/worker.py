import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

import httpx

from . import storage
from .config import settings
from .db import pool

log = logging.getLogger("worker")

GNANI_URL = "https://api.vachana.ai/stt/v3"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
CHUNK_SECONDS = 25  # Gnani REST accepts max 60s, ideal 30s
STT_TRIES = 3

SUMMARY_SYSTEM = (
    "You summarize audio transcripts. Write a clear summary in English: "
    "a 2-3 sentence overview, then bullet points with the key points, "
    "decisions and action items if there are any. Do not invent details."
)


class PermanentError(Exception):
    """Retrying will not help (corrupt file, bad API key...). The message is shown to the user."""


# ---------- job queue (the jobs table) ----------

async def claim_job():
    """Atomically take one queued job. SKIP LOCKED means two workers never grab the same row."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_at = now()
               WHERE id = (SELECT id FROM jobs
                           WHERE status = 'queued' AND run_after <= now()
                           ORDER BY run_after, id
                           FOR UPDATE SKIP LOCKED LIMIT 1)
               RETURNING id, upload_id, attempts, max_attempts"""
        )
        return await cur.fetchone()


async def requeue_stuck_jobs():
    """On startup: a job still 'running' belongs to a worker that died. Queue it again.
    (Assumes a single worker process. With several you'd use locked_at timeouts.)"""
    async with pool.connection() as conn:
        await conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")


async def update_upload(upload_id, **fields):
    cols = ", ".join(f"{k} = %s" for k in fields)  # keys come from our own code, never from users
    async with pool.connection() as conn:
        await conn.execute(
            f"UPDATE uploads SET {cols}, updated_at = now() WHERE id = %s",
            (*fields.values(), upload_id),
        )


async def fail_job(job, message: str, retry: bool):
    can_retry = retry and job["attempts"] < job["max_attempts"]
    delay = 30 * job["attempts"]  # back off: 30s, 60s...
    async with pool.connection() as conn:
        if can_retry:
            await conn.execute(
                """UPDATE jobs SET status = 'queued', last_error = %s,
                   run_after = now() + %s * interval '1 second' WHERE id = %s""",
                (message, delay, job["id"]),
            )
            await conn.execute(
                "UPDATE uploads SET status = 'queued', error_message = %s, updated_at = now() WHERE id = %s",
                (f"{message} Retrying automatically...", job["upload_id"]),
            )
        else:
            await conn.execute(
                "UPDATE jobs SET status = 'failed', last_error = %s WHERE id = %s",
                (message, job["id"]),
            )
            await conn.execute(
                "UPDATE uploads SET status = 'failed', error_message = %s, updated_at = now() WHERE id = %s",
                (message, job["upload_id"]),
            )


async def worker_loop():
    await requeue_stuck_jobs()
    log.info("worker started")
    while True:
        try:
            job = await claim_job()
        except Exception:
            log.exception("could not claim a job")
            await asyncio.sleep(5)
            continue
        if job is None:
            await asyncio.sleep(2)  # nothing to do, check again soon
            continue
        await run_job(job)


async def run_job(job):
    try:
        await process_upload(job["upload_id"])
        async with pool.connection() as conn:
            await conn.execute("UPDATE jobs SET status = 'done' WHERE id = %s", (job["id"],))
    except PermanentError as e:
        await fail_job(job, str(e), retry=False)
    except Exception as e:
        log.exception("job crashed")
        await fail_job(job, f"Something went wrong ({type(e).__name__}).", retry=True)


# ---------- the actual pipeline ----------

def probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise PermanentError("The server is missing ffmpeg, so audio cannot be processed.")
    try:
        duration = float(r.stdout.strip())
    except ValueError:
        raise PermanentError("This file could not be read as audio. It may be corrupted.")
    if duration <= 0:
        raise PermanentError("The audio file is empty.")
    return duration


def split_audio(src: Path, out_dir: Path) -> list[Path]:
    """Convert to 16kHz mono WAV and cut into CHUNK_SECONDS pieces."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
         "-reset_timestamps", "1", str(out_dir / "chunk_%04d.wav")],
        capture_output=True, text=True,
    )
    files = sorted(out_dir.glob("chunk_*.wav"))
    if r.returncode != 0 or not files:
        raise PermanentError("Could not process this audio file. It may be corrupted.")
    return files


def api_message(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"]
    except Exception:
        return r.text[:200]


async def transcribe_chunk(client: httpx.AsyncClient, path: Path, language: str) -> str:
    if not settings.gnani_api_key:
        raise PermanentError("The Gnani API key is not configured on the server.")
    audio = path.read_bytes()
    last = "unknown error"
    for attempt in range(1, STT_TRIES + 1):
        try:
            r = await client.post(
                GNANI_URL,
                headers={"X-API-Key-ID": settings.gnani_api_key},
                files={"audio_file": (path.name, audio, "audio/wav")},
                data={"language_code": language, "format": "transcribe"},
            )
        except httpx.HTTPError as e:  # timeout, connection error...
            last = f"network problem ({type(e).__name__})"
        else:
            if r.status_code == 200:
                return (r.json().get("transcript") or "").strip()
            if r.status_code == 400:
                raise PermanentError(f"The transcription service rejected the audio: {api_message(r)}")
            if r.status_code in (401, 403):
                raise PermanentError("The Gnani API key was rejected or the account is out of credits.")
            last = f"HTTP {r.status_code}"  # 429 / 500 / 503: worth retrying
        if attempt < STT_TRIES:
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"Transcription service failed after {STT_TRIES} tries ({last}).")


async def groq_chat(client: httpx.AsyncClient, system: str, text: str) -> str:
    r = await client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        json={"model": GROQ_MODEL, "temperature": 0.3,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": text}]},
    )
    if r.status_code in (401, 403):
        raise PermanentError("The Groq API key was rejected.")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


async def summarize(transcript: str) -> str:
    if not settings.groq_api_key:
        raise PermanentError("The Groq API key is not configured on the server.")
    async with httpx.AsyncClient(timeout=60) as client:
        pieces = [transcript[i:i + 12000] for i in range(0, len(transcript), 12000)]
        if len(pieces) == 1:
            return await groq_chat(client, SUMMARY_SYSTEM, pieces[0])
        # Very long transcript: summarize each piece, then summarize the summaries.
        partials = [await groq_chat(client, "Summarize this part of a longer transcript in one short paragraph.", p)
                    for p in pieces]
        return await groq_chat(client, SUMMARY_SYSTEM, "\n\n".join(partials))


async def process_upload(upload_id):
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM uploads WHERE id = %s", (upload_id,))
        up = await cur.fetchone()
    if up is None:
        raise PermanentError("Upload record not found.")

    await update_upload(upload_id, status="processing", error_message=None)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        src = tmp / ("input" + Path(up["storage_key"]).suffix)

        await asyncio.to_thread(storage.download_file, up["storage_key"], str(src))
        duration = await asyncio.to_thread(probe_duration, src)
        chunk_files = await asyncio.to_thread(split_audio, src, tmp)

        # One row per chunk. If the job is retried, finished chunks are skipped.
        async with pool.connection() as conn:
            for i in range(len(chunk_files)):
                await conn.execute(
                    """INSERT INTO upload_chunks (upload_id, idx, start_sec)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (upload_id, i, i * CHUNK_SECONDS),
                )
            await conn.execute(
                """UPDATE uploads SET duration_seconds = %s, chunks_total = %s,
                   chunks_done = (SELECT count(*) FROM upload_chunks
                                  WHERE upload_id = %s AND status = 'done'),
                   status = 'transcribing', updated_at = now() WHERE id = %s""",
                (duration, len(chunk_files), upload_id, upload_id),
            )
            cur = await conn.execute(
                "SELECT idx FROM upload_chunks WHERE upload_id = %s AND status = 'done'", (upload_id,)
            )
            already_done = {r["idx"] for r in await cur.fetchall()}

        async with httpx.AsyncClient(timeout=90) as client:
            for i, path in enumerate(chunk_files):
                if i in already_done:
                    continue
                text = await transcribe_chunk(client, path, up["language_code"])
                async with pool.connection() as conn:
                    await conn.execute(
                        "UPDATE upload_chunks SET status = 'done', transcript = %s WHERE upload_id = %s AND idx = %s",
                        (text, upload_id, i),
                    )
                    await conn.execute(
                        "UPDATE uploads SET chunks_done = chunks_done + 1, updated_at = now() WHERE id = %s",
                        (upload_id,),
                    )

    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT string_agg(NULLIF(transcript, ''), ' ' ORDER BY idx) AS t
               FROM upload_chunks WHERE upload_id = %s""",
            (upload_id,),
        )
        transcript = ((await cur.fetchone())["t"] or "").strip()

    await update_upload(upload_id, transcript=transcript, status="summarizing")
    summary = await summarize(transcript) if transcript else "No speech was detected in this audio."
    await update_upload(upload_id, summary=summary, status="done", error_message=None)