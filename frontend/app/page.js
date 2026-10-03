"use client"; // this page uses state and browser features, so it runs in the browser

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createUpload, uploadToBucket, completeUpload, listUploads } from "../lib/api";

const LANGUAGES = [
  ["en-IN", "English"], ["hi-IN", "Hindi"], ["bn-IN", "Bengali"], ["gu-IN", "Gujarati"],
  ["kn-IN", "Kannada"], ["ml-IN", "Malayalam"], ["mr-IN", "Marathi"], ["pa-IN", "Punjabi"],
  ["ta-IN", "Tamil"], ["te-IN", "Telugu"],
];
const ALLOWED = [".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a"];
const MAX_MB = 200;

export default function Home() {
  const router = useRouter();
  const [file, setFile] = useState(null);
  const [language, setLanguage] = useState("en-IN");
  const [stage, setStage] = useState("idle"); // idle | preparing | uploading | finalizing
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState("");
  const [uploads, setUploads] = useState([]);
  const [listError, setListError] = useState("");

  async function refresh() {
    try {
      setUploads(await listUploads());
      setListError("");
    } catch (e) {
      setListError(e.message);
    }
  }

  // Load the list now, then every 5 seconds so statuses stay current.
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (!file) return setError("Please choose an audio file first.");
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!ALLOWED.includes(ext)) return setError(`Unsupported file type. Use one of: ${ALLOWED.join(", ")}`);
    if (file.size === 0) return setError("That file is empty.");
    if (file.size > MAX_MB * 1024 * 1024) return setError(`File is too large. The maximum is ${MAX_MB} MB.`);

    try {
      setStage("preparing");
      const created = await createUpload(file, language);
      setStage("uploading");
      setPercent(0);
      await uploadToBucket(created.upload_url, file, created.content_type, setPercent);
      setStage("finalizing");
      await completeUpload(created.id);
      router.push(`/uploads/${created.id}`);
    } catch (err) {
      setError(err.message);
      setStage("idle");
    }
  }

  const busy = stage !== "idle";

  return (
    <>
      <div className="card">
        <h1>Audio Notes</h1>
        <p className="muted">Upload a recording and get a transcript and a summary.</p>
        <form onSubmit={handleSubmit}>
          <label>Audio file ({ALLOWED.join(", ")})
            <input type="file" accept="audio/*,.m4a,.aac,.flac" disabled={busy}
                   onChange={(e) => setFile(e.target.files[0] || null)} />
          </label>
          <label>Language spoken in the audio
            <select value={language} disabled={busy} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </label>
          <button type="submit" disabled={busy}>{busy ? "Working…" : "Upload and transcribe"}</button>
        </form>

        {stage === "preparing" && <p className="muted">Preparing upload…</p>}
        {stage === "uploading" && (
          <>
            <p className="muted">Uploading… {percent}%</p>
            <div className="bar"><div style={{ width: `${percent}%` }} /></div>
          </>
        )}
        {stage === "finalizing" && <p className="muted">Upload finished. Starting processing…</p>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="card">
        <h2>Past uploads</h2>
        {listError && <div className="warn">Could not load past uploads: {listError}</div>}
        {!listError && uploads.length === 0 && <p className="muted">No uploads yet.</p>}
        {uploads.map((u) => (
          <div className="row" key={u.id}>
            <div>
              <Link href={`/uploads/${u.id}`}>{u.filename}</Link>
              <div className="muted">{new Date(u.created_at).toLocaleString()}</div>
            </div>
            <span className={`badge ${u.status}`}>{u.status}</span>
          </div>
        ))}
      </div>
    </>
  );
}