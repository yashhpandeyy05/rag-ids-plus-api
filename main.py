from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "RAG-IDS+ API"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".log", ".csv", ".json"}
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# Set FRONTEND_ORIGINS to comma-separated exact origins, e.g.
# https://your-site.example,https://another.example
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app = FastAPI(
    title=APP_NAME,
    description="Research prototype API for dataset ingestion in RAG-IDS+.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


class ErrorResponse(BaseModel):
    detail: str


class IngestionResponse(BaseModel):
    status: str
    dataset_id: str
    filename: str
    file_type: str
    size_bytes: int
    records_parsed: int
    chunks_created: int
    chunk_size_chars: int
    chunk_overlap_chars: int
    storage: str = "temporary; not persisted"
    message: str


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping character chunks."""
    if size < 1:
        raise ValueError("CHUNK_SIZE must be at least 1.")
    if overlap < 0 or overlap >= size:
        raise ValueError("CHUNK_OVERLAP must be >= 0 and smaller than CHUNK_SIZE.")
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    step = size - overlap
    for start in range(0, len(text), step):
        part = text[start : start + size].strip()
        if part:
            chunks.append(part)
        if start + size >= len(text):
            break
    return chunks


def parse_csv_text(text: str) -> tuple[str, int]:
    """Convert CSV rows into readable text; first row is treated as a header."""
    try:
        rows = list(csv.reader(text.splitlines()))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc
    if not rows:
        return "", 0
    header = rows[0]
    body_rows = rows[1:] if len(rows) > 1 else []
    lines = []
    for row in body_rows:
        if not row or not any(cell.strip() for cell in row):
            continue
        if header and len(header) == len(row):
            lines.append("; ".join(f"{key.strip()}: {value.strip()}" for key, value in zip(header, row)))
        else:
            lines.append("; ".join(cell.strip() for cell in row))
    return "\n".join(lines), len(body_rows)


def parse_json_text(text: str) -> tuple[str, int]:
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON at line {exc.lineno}, column {exc.colno}.") from exc

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict) and isinstance(data.get("records"), list):
        records = data["records"]
    else:
        records = [data]

    lines: list[str] = []
    for item in records:
        if isinstance(item, (dict, list)):
            lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        else:
            lines.append(str(item))
    return "\n".join(lines), len(records)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": APP_NAME,
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "version": "0.1.0"}


@app.post(
    "/api/datasets/ingest",
    response_model=IngestionResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
async def ingest_dataset(file: UploadFile = File(...)) -> IngestionResponse:
    """Parse a dataset and count real chunks. Files are not persisted after the request."""
    original_name = Path(file.filename or "dataset").name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        await file.close()
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{extension or '(no extension)'}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    # Stream to a temporary file to avoid loading the whole upload into RAM.
    total_bytes = 0
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ragids_", suffix=extension, delete=False) as temp:
            temp_path = Path(temp.name)
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                total_bytes += len(block)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the configured {MAX_UPLOAD_MB} MB limit.",
                    )
                temp.write(block)

        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        try:
            text = temp_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="File must be valid UTF-8 text.") from exc

        if extension in {".txt", ".log"}:
            parsed_text = text
            records_parsed = sum(1 for line in text.splitlines() if line.strip())
        elif extension == ".csv":
            parsed_text, records_parsed = parse_csv_text(text)
        else:
            parsed_text, records_parsed = parse_json_text(text)

        chunks = chunk_text(parsed_text)
        return IngestionResponse(
            status="ingested",
            dataset_id=str(uuid4()),
            filename=original_name,
            file_type=extension[1:],
            size_bytes=total_bytes,
            records_parsed=records_parsed,
            chunks_created=len(chunks),
            chunk_size_chars=CHUNK_SIZE,
            chunk_overlap_chars=CHUNK_OVERLAP,
            message="Dataset parsed and chunked for this request. No dataset or chunks were permanently stored.",
        )
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
