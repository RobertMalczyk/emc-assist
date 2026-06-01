#!/usr/bin/env python3
"""
Skeleton script for building a local source manifest.

MVP behavior:
- scan knowledge/raw_sources,
- match files by SOURCE_ID prefix,
- combine with seed JSONL metadata,
- write knowledge/processed/source_manifest.jsonl.

Claude Code should implement this in M0/M1.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "knowledge" / "raw_sources"
OUT = ROOT / "knowledge" / "processed" / "source_manifest.jsonl"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(RAW.glob("*")):
        if not path.is_file():
            continue
        source_id = path.name.split("__", 1)[0]
        entries.append({
            "source_id": source_id,
            "local_path": str(path.relative_to(ROOT)),
            "file_type": path.suffix.lower().lstrip("."),
            "allowed_use": "link_and_summary",
            "license_notes": "Public/user-provided local source; verify before redistribution."
        })
    with OUT.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"Wrote {len(entries)} entries to {OUT}")


if __name__ == "__main__":
    main()
