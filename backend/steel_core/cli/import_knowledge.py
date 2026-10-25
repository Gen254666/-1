from __future__ import annotations

import argparse
import hashlib
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from steel_core.knowledge.service import get_client, ingest_document


def _doc_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="批量导入知识库 Markdown/TXT")
    parser.add_argument("--dir", type=Path, default=Path("/app/knowledge"))
    parser.add_argument("--collection", default="kb_public")
    parser.add_argument("--doc-type", default="internal_rule")
    parser.add_argument("--source", default="local")
    parser.add_argument("--effective-date", type=date.fromisoformat, default=None)
    parser.add_argument("--expire-date", type=date.fromisoformat, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files = sorted(
        path
        for path in args.dir.glob("*")
        if path.is_file()
        and path.suffix.lower() in {".md", ".txt"}
        and path.name.lower() != "readme.md"
        and not path.name.startswith("_")
    )
    if not files:
        print(f"没有可导入文件: {args.dir}")
        return 1

    if args.dry_run:
        for path in files:
            text = path.read_text(encoding="utf-8")
            print(f"{path.name}: {len(text)} chars")
        return 0

    client = get_client(get_settings().chroma_path)
    collection = client.get_or_create_collection(args.collection)
    total_chunks = 0
    for path in files:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        doc_id = f"knowledge-{hashlib.sha1(path.name.encode('utf-8')).hexdigest()[:16]}"
        title = _doc_title(text, path.stem)
        chunks = ingest_document(
            collection,
            doc_id=doc_id,
            title=title,
            text=text,
            doc_type=args.doc_type,
            source=args.source,
            effective_date=args.effective_date,
            expire_date=args.expire_date,
        )
        total_chunks += chunks
        print(f"{path.name}: {title} -> {chunks} chunks")
    print(f"done: {len(files)} files, {total_chunks} chunks, collection={args.collection}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
