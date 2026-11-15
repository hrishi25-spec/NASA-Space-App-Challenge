# 0006 — Hugging Face bucket streaming and stateless serverless instances

- **Date:** 2026-11-15
- **Status:** Accepted

## Context

Pyro-Harmony was designed to run against local NASA FIRMS active-fire CSV exports or sync the harmonized year parquet from the public Hugging Face bucket `hriishiibanerjee/FIRMS_DEMO` into `<repo>/.data/hf`. In deployment on Vercel Serverless Functions (`https://pyro-harmony.vercel.app`), this model failed for two reasons:
1. **Read-only filesystem:** The serverless execution environment does not allow writing to the application directory (`.data/hf`), making local file syncing impossible. While `/tmp` is writable, it is capped at ~500 MB and ephemeral.
2. **Stateless serverless instances:** The dataset originally resided in a process-global DataFrame loaded on explicit operator request. In serverless deployment, each HTTP request may hit a fresh, cold instance with an empty DataFrame, showing "No local archives found" and an empty standby card.

Furthermore, downloading the entire 466 MB parquet file on cold start would exceed serverless function timeouts and execution memory limits.

## Decision

1. **Ranged HTTP streaming mode (`FIRECAL_HF_MODE=stream`):**
   - Read the remote bucket directly over HTTP via `huggingface_hub.HfFileSystem` and `pyarrow.parquet.ParquetFile`.
   - Take the parquet schema, byte size, and dataset coverage strictly from the parquet footer and a small sample of row groups without downloading the file.
   - For queries and loading, perform ranged reads of only the row groups selected by the spread algorithm (`FIRECAL_REMOTE_LIMIT`, default 400,000 rows across ~20 row groups), transferring ~80 MB instead of the full 466 MB.
   - Automatically fall back to streaming mode when the cache root is not writable (`is_root_writable() == False`), preserving the full sync path on local workstations.

2. **Single-flight idempotent auto-load (`FIRECAL_AUTOLOAD=1`):**
   - Data endpoints (`/meta`, `/calendar`, `/points`, `/clusters`, etc.) lazily trigger `ensure_autoloaded()` on first need if the in-memory `DF` is empty and no local archives exist.
   - A concurrency lock (`_AUTOLOAD_LOCK`) ensures single-flight execution: concurrent cold requests wait for the in-flight load rather than initiating duplicate transfers. If the wait times out, the server answers HTTP 503 with a `Retry-After` header.
   - Explicit user clearing (`DELETE /data`) sets a persistent `_USER_CLEARED` flag so the server never resurrects cleared datasets.
   - `FIRECAL_AUTOLOAD` defaults to OFF (`0`) so local development and offline test suites maintain identical deterministic behavior.

3. **Stateless instance caveat and frontend feedback:**
   - Display "Loading the shared record from Hugging Face…" while autoload or remote listing is in flight.
   - Automatically retry HTTP 503 responses with exponential backoff and `Retry-After` honoring.
   - Clarify in the UI that manual CSV uploads live in instance memory and may not persist across separate serverless instances.

## Consequences

- The application opens immediately on the harmonized year record on Vercel without requiring local disk storage or manual dataset selection.
- Memory and network usage remain bounded during cold starts (~80 MB transferred, completed within ~41 s on a cold load).
- All offline test suites remain strictly disconnected from the network via test stubs.
