const FLOW_STEPS = [
  {
    number: "01",
    title: "Choose a recording",
    text: "The Next.js app checks the audio format, selected language, and 200 MB size limit before starting.",
  },
  {
    number: "02",
    title: "Create an upload",
    text: "FastAPI validates the request, creates an uploading record in Postgres, and returns a signed storage URL.",
  },
  {
    number: "03",
    title: "Upload directly to storage",
    text: "The browser sends the audio straight to the S3-compatible bucket, so large file bytes do not pass through the API.",
  },
  {
    number: "04",
    title: "Verify and queue",
    text: "The browser tells FastAPI when the transfer finishes. The API checks the stored object and adds a job to the Postgres queue.",
  },
  {
    number: "05",
    title: "Transcribe in the background",
    text: "A worker downloads and prepares the recording, then sends its audio chunks to Gnani's ASR API and saves each result.",
  },
  {
    number: "06",
    title: "Save the notes",
    text: "The worker joins the chunk transcripts in order, asks Groq to summarize them, and saves the transcript and summary.",
  },
];

export default function Architecture() {
  return (
    <div className="architecture-page">
      <section className="card architecture-hero">
        <div>
          <p className="architecture-eyebrow">Audio Notes / System architecture</p>
          <h1>From a recording to useful notes.</h1>
          <p className="architecture-lede">
            Audio is uploaded directly to object storage. A background worker
            turns it into a transcript with Gnani, then creates a concise
            summary with Groq.
          </p>
        </div>
        <a
          className="architecture-repo-link"
          href="https://github.com/123-piyu/audio-notes"
          target="_blank"
          rel="noreferrer"
        >
          View the GitHub repository
        </a>
      </section>

      <section className="card architecture-section" aria-labelledby="flow-title">
        <div className="architecture-section-heading">
          <p className="architecture-eyebrow">01 / Request lifecycle</p>
          <h2 id="flow-title">The path from upload to result</h2>
          <p className="muted">
            The API handles the short setup steps; audio processing continues
            as a queued job.
          </p>
        </div>
        <ol className="architecture-flow">
          {FLOW_STEPS.map((step) => (
            <li className="architecture-step" key={step.number}>
              <span className="architecture-step-number" aria-hidden="true">
                {step.number}
              </span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="card architecture-section" aria-labelledby="long-audio-title">
        <div className="architecture-section-heading">
          <p className="architecture-eyebrow">02 / Long audio</p>
          <h2 id="long-audio-title">Process in small, resumable pieces</h2>
          <p className="muted">
            The upload limit is 200 MB. Longer recordings are split before
            transcription rather than sent to the speech service as one request.
          </p>
        </div>
        <div className="architecture-detail-grid">
          <article className="architecture-detail">
            <span className="architecture-detail-label">Prepare</span>
            <p>
              The worker checks the duration with ffprobe, then ffmpeg converts
              the audio to mono 16 kHz WAV and cuts it into 25-second chunks.
            </p>
          </article>
          <article className="architecture-detail">
            <span className="architecture-detail-label">Transcribe</span>
            <p>
              Chunks are sent to Gnani one at a time in the selected language.
              Each completed transcript and its chunk status are saved in
              Postgres.
            </p>
          </article>
          <article className="architecture-detail">
            <span className="architecture-detail-label">Resume and summarize</span>
            <p>
              If a job is retried, finished chunks are skipped. The worker
              combines results in order and, for long transcripts, summarizes
              smaller sections before producing the final summary with Groq.
            </p>
          </article>
        </div>
      </section>

      <section className="card architecture-section" aria-labelledby="storage-title">
        <div className="architecture-section-heading">
          <p className="architecture-eyebrow">03 / Data and responsibilities</p>
          <h2 id="storage-title">Where each part lives</h2>
        </div>
        <div className="architecture-detail-grid">
          <article className="architecture-detail">
            <span className="architecture-detail-label">Postgres</span>
            <p>
              Upload metadata, processing status, chunk results, transcripts,
              summaries, and queued jobs.
            </p>
          </article>
          <article className="architecture-detail">
            <span className="architecture-detail-label">Object storage</span>
            <p>
              The original audio file lives in an S3-compatible bucket under a
              unique key. The API issues a short-lived signed upload URL.
            </p>
          </article>
          <article className="architecture-detail">
            <span className="architecture-detail-label">Worker and services</span>
            <p>
              A temporary worker directory holds the downloaded audio and
              converted chunks during processing; it is cleaned up afterward.
              Gnani receives audio chunks, and Groq receives transcript text.
            </p>
          </article>
        </div>
      </section>

      <section className="card architecture-section" aria-labelledby="timing-title">
        <div className="architecture-section-heading">
          <p className="architecture-eyebrow">04 / What runs when</p>
          <h2 id="timing-title">Fast setup, background processing</h2>
        </div>
        <div className="architecture-detail-grid architecture-timing-grid">
          <article className="architecture-detail">
            <span className="architecture-detail-label">Synchronous</span>
            <p>
              Request validation, upload record creation, signed URL creation,
              the browser-to-bucket transfer, and the completion check and job
              enqueue.
            </p>
          </article>
          <article className="architecture-detail">
            <span className="architecture-detail-label">Background</span>
            <p>
              Downloading and converting audio, chunk transcription, transcript
              assembly, and summary generation. These steps do not hold the
              upload request open.
            </p>
          </article>
        </div>
        <p className="architecture-status-note">
          The upload page polls the API for status every 2.5 seconds and shows
          chunk-based progress. Failed processing is shown in the UI; jobs are
          retried automatically up to three times.
        </p>
      </section>

      <section className="card architecture-section" aria-labelledby="next-title">
        <div className="architecture-section-heading">
          <p className="architecture-eyebrow">05 / With more time</p>
          <h2 id="next-title">What I would improve next</h2>
        </div>
        <p className="architecture-next-copy">
          I would run the worker as a separately scalable service instead of
          starting it with the FastAPI application, add versioned database
          migrations, and expand automated tests and monitoring for queue delay,
          retries, and long-file processing.
        </p>
      </section>
    </div>
  );
}
