# Audio Notes

Audio Notes is a web app for uploading a recording and getting back its
transcript and an AI-generated summary. The frontend is built with Next.js, the
API with FastAPI, and PostgreSQL stores upload metadata, processing state, and
results. Audio files are kept in an S3-compatible object-storage bucket.

## Features

- Upload `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, and `.m4a` audio files up to
  200 MB.
- Select one of ten supported Indian languages: Bengali, English, Gujarati,
  Hindi, Kannada, Malayalam, Marathi, Punjabi, Tamil, or Telugu.
- Upload directly from the browser to object storage using a short-lived
  signed URL, with upload progress.
- Transcribe recordings with Gnani's ASR API.
- Generate an English summary of the transcript with Groq.
- See processing status and transcription progress, and reopen recent uploads.
- Retry transient background-job failures and resume without retranscribing
  chunks that have already completed.

## How it works

1. The Next.js app validates the chosen file and asks the FastAPI API to create
   an upload.
2. The API creates an upload record in PostgreSQL and returns a signed URL.
   The browser uploads the audio directly to the S3-compatible bucket.
3. After the upload completes, the browser calls the API to verify the stored
   object and enqueue a job in PostgreSQL.
4. A background worker downloads the audio to a temporary directory. It uses
   `ffprobe` to inspect the recording and `ffmpeg` to convert it to mono,
   16 kHz WAV, then splits it into 25-second chunks.
5. The worker sends each chunk to Gnani, saving completed chunk transcripts
   and progress in PostgreSQL. It joins the transcripts in order and sends the
   result to Groq for summarization. Long transcripts are summarized in
   sections before the final summary is generated.
6. The upload page polls the API for updates and displays the status, summary,
   transcript, or any reported processing error.

The API request handles upload setup and verification; transcription and
summarization happen in the background. The job queue, upload records, chunk
results, transcript, and summary are stored in PostgreSQL. The original audio
is stored in the bucket. Temporary audio-processing files are removed when
processing finishes.

The worker currently runs as an asyncio task in the FastAPI process. Jobs have
up to three attempts with a delay between retries. PostgreSQL's
`FOR UPDATE SKIP LOCKED` is used to claim jobs safely. For larger deployments,
the worker could be separated into its own independently scalable service.

See the [architecture page](frontend/app/architecture/page.js) in the app for a step-by-step
overview.

## Requirements

- Python 3.12 (the backend container image is based on Python 3.12)
- Node.js 20.9 or later and npm
- PostgreSQL 13 or later
- `ffmpeg` and `ffprobe` available on the backend's `PATH`
- An S3-compatible bucket and its endpoint and credentials
- A Gnani API key
- A Groq API key

## Run locally

### 1. Start PostgreSQL

The included Compose file starts PostgreSQL for local development:

```powershell
docker compose -f backend/docker-compose.yml up -d postgres
```

It creates a local database named `audionotes`, with username and password
`postgres`, on port `5432`. The schema is applied automatically when the
PostgreSQL data volume is first initialized. The backend also applies the
idempotent `backend/schema.sql` at startup.

> The Compose file starts PostgreSQL only. Configure an S3-compatible storage
> service separately and create a bucket before starting the backend.

### 2. Configure the backend

Create `backend/.env` with your own local connection details and API
credentials:

```dotenv
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/audionotes

S3_ENDPOINT_URL=https://your-s3-compatible-endpoint
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_BUCKET=your-bucket-name
S3_REGION=auto

CORS_ORIGINS=http://localhost:3000
MAX_UPLOAD_MB=200

GNANI_API_KEY=your-gnani-api-key
GROQ_API_KEY=your-groq-api-key
```

Use the endpoint, region, bucket, and credentials issued by your storage
provider. Configure the bucket's CORS policy to allow browser `PUT` requests
from `http://localhost:3000` and to allow the `Content-Type` request header.
Never commit `.env` files or put provider secrets in frontend environment
variables.

Install FFmpeg for your operating system and make sure both `ffmpeg` and
`ffprobe` can be run from the terminal.

Create a Python environment and install the backend requirements:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start the API from the `backend` directory so the settings loader finds
`backend/.env`:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API creates the database connection pool, applies the schema, and starts
the background worker when it starts. The API health check is available at
[`http://localhost:8000/health`](http://localhost:8000/health), and the
interactive API docs are at [`http://localhost:8000/docs`](http://localhost:8000/docs).

### 3. Start the frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [`http://localhost:3000`](http://localhost:3000). The frontend defaults
to an API at `http://localhost:8000`. To use a different API URL, create
`frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=https://your-api-host
```

Restart the Next.js development server after changing environment variables.
Set the backend's `CORS_ORIGINS` to the exact frontend origin.

## API endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | API health check |
| `POST` | `/uploads` | Validate upload details, create an upload record, and return a signed URL |
| `POST` | `/uploads/{id}/complete` | Verify the stored file and enqueue its processing job |
| `GET` | `/uploads` | List the 50 most recent uploads |
| `GET` | `/uploads/{id}` | Get an upload's status, progress, transcript, summary, and error |

The upload lifecycle is `uploading` → `queued` → `processing` →
`transcribing` → `summarizing` → `done`. Processing may end in `failed` if
the error cannot be recovered from.

## Configuration reference

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | Yes | PostgreSQL connection URL |
| `S3_ENDPOINT_URL` | Yes | S3-compatible object-storage endpoint |
| `S3_ACCESS_KEY` | Yes | Object-storage access key |
| `S3_SECRET_KEY` | Yes | Object-storage secret key |
| `S3_BUCKET` | Yes | Bucket used for uploaded audio |
| `S3_REGION` | No | Storage region; defaults to `auto` |
| `CORS_ORIGINS` | No | Comma-separated allowed frontend origins; defaults to `http://localhost:3000` |
| `MAX_UPLOAD_MB` | No | Maximum upload size in MiB; defaults to `200` |
| `GNANI_API_KEY` | No* | Gnani speech-to-text API key |
| `GROQ_API_KEY` | No* | Groq API key for transcript summaries |
| `NEXT_PUBLIC_API_URL` | No | Frontend API base URL; defaults to `http://localhost:8000` |

`GNANI_API_KEY` and `GROQ_API_KEY` are optional at application startup, but
their respective processing steps require them. Keep these credentials on the
backend only.

## Development checks

Run the frontend linter and production build from the repository root:

```powershell
npm --prefix frontend run lint
npm --prefix frontend run build
```

## Deployment notes

Deploy the frontend and FastAPI backend as separate services, and provision a
managed PostgreSQL database and persistent S3-compatible object-storage bucket.
Configure the backend environment variables above, set `CORS_ORIGINS` to the
deployed frontend's origin, and set the frontend's `NEXT_PUBLIC_API_URL` to the
deployed API URL.

The current API does not implement user authentication or per-user data
isolation. Add authentication and access controls before exposing it to
untrusted users.

The backend image definition is in [`backend/DockerFile`](backend/DockerFile);
it installs FFmpeg. Ensure the deployed backend has `ffmpeg` and `ffprobe`
available, outbound access to the storage, Gnani, and Groq services, and enough
temporary disk space to process an uploaded recording. Run a single backend
worker process with the current in-process job worker; scaling the API to
multiple processes or replicas also starts multiple worker loops.

## Repository layout

```text
backend/
  app/
    config.py       Environment-based backend settings
    db.py           PostgreSQL connection pool and schema initialization
    main.py         FastAPI endpoints and application lifecycle
    storage.py      S3-compatible presigned uploads and file downloads
    worker.py       Job queue, audio processing, transcription, and summaries
  docker-compose.yml
  DockerFile
  requirements.txt
  schema.sql

frontend/
  app/
    architecture/   Architecture overview page
    uploads/[id]/   Upload status, transcript, and summary
    page.js         Upload form and recent uploads
  lib/api.js        Browser-side API and direct-to-storage upload helpers
```

## License

No license file is currently included in this repository.
