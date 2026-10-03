const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Wrapper around fetch that turns every failure into a readable Error message.
async function request(path, options) {
  let res;
  try {
    res = await fetch(`${API}${path}`, options);
  } catch {
    throw new Error("Cannot reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let message = `Request failed (HTTP ${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {}
    throw new Error(message);
  }
  return res.json();
}

export function createUpload(file, languageCode) {
  return request("/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "audio/mpeg",
      size_bytes: file.size,
      language_code: languageCode,
    }),
  });
}

export const completeUpload = (id) => request(`/uploads/${id}/complete`, { method: "POST" });
export const listUploads = () => request("/uploads");
export const getUpload = (id) => request(`/uploads/${id}`);

// Sends the file straight to the bucket using the signed URL.
// XMLHttpRequest (not fetch) because it reports upload progress.
export function uploadToBucket(url, file, contentType, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType); // must match what the URL was signed with
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload to storage failed (HTTP ${xhr.status}). Please try again.`));
    xhr.onerror = () => reject(new Error("Upload failed because of a network error. Please try again."));
    xhr.send(file);
  });
}