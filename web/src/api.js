/* Fetch helpers — every call returns parsed JSON or throws with the API's detail. */

async function handle(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch { /* keep default */ }
    throw new Error(detail);
  }
  return res.json();
}

export const get = (url) => fetch(url).then(handle);

export const post = (url, body) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  }).then(handle);

export const postFile = (url, file, filename) => {
  const fd = new FormData();
  fd.append("file", file, filename || file.name || "upload");
  return fetch(url, { method: "POST", body: fd }).then(handle);
};

/* Streaming POST: the response body arrives as plain-text chunks which are fed
   to onChunk as they land. Resolves with the complete text. */
export async function postStream(url, body, onChunk) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let full = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    if (text) { full += text; onChunk?.(text, full); }
  }
  return full;
}
