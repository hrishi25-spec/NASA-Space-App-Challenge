#!/usr/bin/env python3
"""Key-free helper to download the multi-year FIRMS archive into `.data/`.

This is the key-free path the README documents: it pulls the project's Hugging Face bucket
(configured via `FIRECAL_HF_BUCKET`, defaulting to `hriishiibanerjee/FIRMS_DATA`) into
`.data/` using the same function the console uses when the local folder is empty.

It is the documented key-free path to a multi-year archive that `train_forecast.py` and 
`train.py` can read — no `FIRMS_MAP_KEY` required. 

On this machine it is not functional yet: the bucket `hriishiibanerjee/FIRMS_DATA` is 
either private or deleted, so both the Python client path and the direct anonymous HTTP 
path return "unreachable / empty" (tested from this environment). Until the bucket is 
public again, or `FIRECAL_HF_BUCKET` is pointed at one that is, this helper exits with 
a clear message instead of pretending the archive is present.

Usage:
  python scripts/fetch_multi_year.py
  python scripts/fetch_multi_year.py --out .data
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firecal" / "backend"))

try:
    import archives  # type: ignore  # noqa: E402
except Exception as e:  # pragma: no cover
    print(f"failed to import archives: {e}")
    sys.exit(2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / ".data"),
        help="target directory for the archive (default: repo's .data/)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=archives.HF_SYNC_TIMEOUT,
        help=f"sync timeout in seconds (default: {archives.HF_SYNC_TIMEOUT})",
    )
    args = parser.parse_args(argv)
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)

    print(f"bucket: {archives.bucket_id()}")
    print(f"target: {root}")

    ok, msg = archives.hf_pull(root, timeout=args.timeout)
    if ok:
        print(f"ok: {msg}")
        return 0
    print(f"failed: {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main(argv=None))


