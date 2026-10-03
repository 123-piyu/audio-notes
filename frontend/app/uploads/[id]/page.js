"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getUpload } from "../../../lib/api";

const LABELS = {
  uploading: "Waiting for the file to finish uploading…",
  queued: "In the queue. Processing starts in a moment…",
  processing: "Preparing your audio…",
  transcribing: "Transcribing…",
  summarizing: "Writing the summary…",
  done: "Done",
  failed: "Failed",
};

// Rough overall progress. Transcribing is the long part, so it uses the chunk counter.
function progressOf(u) {
  switch (u.status) {
    case "uploading": return 2;
    case "queued": return 5;
    case "processing": return 10;
    case "transcribing":
      return 10 + (u.chunks_total ? Math.round((80 * u.chunks_done) / u.chunks_total) : 0);
    case "summarizing": return 95;
    case "done": return 100;
    default: return 0;
  }
}

export default function UploadPage() {
  const { id } = useParams();
  const [upload, setUpload] = useState(null);
  const [pollError, setPollError] = useState("");

  // Ask the backend for the latest state every 2.5 s until the job finishes.
  useEffect(() => {
    let stopped = false;
    let timer;

    async function poll() {
      try {
        const u = await getUpload(id);
        if (stopped) return;
        setUpload(u);
        setPollError("");
        if (u.status === "done" || u.status === "failed") return; // finished: stop asking
      } catch (e) {
        if (stopped) return;
        setPollError(e.message); // keep trying, the server may be briefly unreachable
      }
      timer = setTimeout(poll, 2500);
    }

    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [id]);

  if (!upload) {
    return pollError
      ? <div className="error">{pollError} <Link href="/">Back to home</Link></div>
      : <p className="muted">Loading…</p>;
  }

  const running = !["done", "failed"].includes(upload.status);

  return (
    <>
      <p><Link href="/">← All uploads</Link></p>
      <div className="card">
        <h1>{upload.filename}</h1>
        <span className={`badge ${upload.status}`}>{upload.status}</span>
        <span className="muted"> · {new Date(upload.created_at).toLocaleString()}</span>

        {pollError && <div className="warn">Connection problem, retrying… ({pollError})</div>}

        {running && (
          <>
            <p>{LABELS[upload.status]}
              {upload.status === "transcribing" && upload.chunks_total > 0 &&
                ` (part ${upload.chunks_done} of ${upload.chunks_total})`}
            </p>
            <div className="bar"><div style={{ width: `${progressOf(upload)}%` }} /></div>
            <p className="muted">You can leave this page; processing continues on the server.</p>
          </>
        )}

        {upload.error_message && (
          <div className={upload.status === "failed" ? "error" : "warn"}>
            {upload.status === "failed" ? "Processing failed: " : ""}{upload.error_message}
          </div>
        )}
      </div>

      {upload.summary && (
        <div className="card">
          <h2>Summary</h2>
          <div className="text">{upload.summary}</div>
        </div>
      )}

      {upload.status === "done" && (
        <div className="card">
          <h2>Transcript</h2>
          <div className="text">{upload.transcript || "No speech was detected in this audio."}</div>
        </div>
      )}
    </>
  );
}