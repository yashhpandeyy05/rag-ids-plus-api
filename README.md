# RAG-IDS+ API (research prototype)

A small FastAPI service for validating, parsing, and chunking TXT, LOG, CSV, and JSON datasets.

## What it does now

- `GET /health`: health check.
- `GET /docs`: interactive API documentation.
- `POST /api/datasets/ingest`: accepts a multipart file field named `file`, parses supported UTF-8 text files, creates overlapping text chunks in memory, and returns real counts.

## Important limitations

- This is a dataset-ingestion starter, not a complete RAG security research implementation.
- It does **not** implement membership inference, poisoning, retrieved-content leakage, RAGuard, or the proposed RAG-IDS+ Enhanced defense.
- Uploaded files and chunks are temporary. The API returns counts and a generated dataset ID, but does not persist the dataset or chunks across requests. Do not treat the returned ID as a retrievable stored dataset.
- The configured 100 MB limit is enforced in application code, but the hosting platform or reverse proxy may impose a smaller request limit.
- Only UTF-8 text formats are supported. CSV rows are converted to labelled text when headers match row lengths. JSON lists, objects, and objects with a `records` list are supported.

## Run locally (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FRONTEND_ORIGINS="http://localhost:5173"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If PowerShell blocks virtual-environment activation, use Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

Then open:

- Health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

## Deploy on Render

1. Create a GitHub repository and upload these files.
2. In Render, create a **Web Service** connected to that repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables:
   - `FRONTEND_ORIGINS` = the exact deployed frontend origin, without a path. For multiple origins, separate with commas.
   - `MAX_UPLOAD_MB` = `100` (optional)
   - `CHUNK_SIZE` = `1000` (optional)
   - `CHUNK_OVERLAP` = `150` (optional)
6. Deploy and verify `https://YOUR-SERVICE.onrender.com/health`.

Do not set CORS to `*` in production unless you have deliberately reviewed the security implications. CORS is not authentication.

## Connect the frontend

Send a `POST` request to:

`https://YOUR-SERVICE.onrender.com/api/datasets/ingest`

Use `FormData` with a single `file` field. Do not manually set the `Content-Type` header when sending `FormData`; the browser must add the multipart boundary.

Example:

```ts
const formData = new FormData();
formData.append("file", file);

const response = await fetch(
  `${import.meta.env.VITE_API_BASE_URL}/api/datasets/ingest`,
  { method: "POST", body: formData }
);

const body = await response.json().catch(() => null);
if (!response.ok) {
  throw new Error(body?.detail ?? `Upload failed (HTTP ${response.status})`);
}
if (!body || body.status !== "ingested") {
  throw new Error("The backend did not confirm ingestion.");
}
```

Set `VITE_API_BASE_URL` to the backend base URL in the frontend hosting environment, then rebuild/redeploy the frontend. Never put private API keys or service-role secrets in frontend environment variables.
