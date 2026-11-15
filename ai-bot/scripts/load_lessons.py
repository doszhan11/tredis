"""Load lesson materials into lessons_kb.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python scripts/load_lessons.py lessons/

Every .md or .txt file is one lesson; the first line (without '#') is the lesson name.
Text is split on blank lines into chunks of about 900 characters. Re-running replaces that lesson's chunks.
Optional env: LESSON_LANG (kk|ru|en, default kk), COURSE (e.g. "GENESIS").
Writes to the shared lessons_kb table: course, lesson, chunk_index, lang, content (content_tsv is generated).
"""
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tredis.db import auth_headers  # noqa: E402

CHUNK = 900


def chunks(text: str):
    buf = ""
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        if buf and len(buf) + len(para) > CHUNK:
            yield buf
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        yield buf


def main(folder: str):
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_KEY"]
    h = auth_headers(key)
    with httpx.Client(base_url=f"{url}/rest/v1", headers=h, timeout=30) as c:
        for f in sorted(Path(folder).glob("*")):
            if f.suffix.lower() not in (".md", ".txt"):
                continue
            lines = f.read_text(encoding="utf-8").strip().splitlines()
            if not lines:
                continue
            lesson, body = lines[0].lstrip("# ").strip(), "\n".join(lines[1:])
            lang, course = os.environ.get("LESSON_LANG", "kk"), os.environ.get("COURSE") or None
            rows = [{"course": course, "lesson": lesson, "chunk_index": i, "lang": lang, "content": ch}
                    for i, ch in enumerate(chunks(body))]
            c.delete("/lessons_kb", params={"lesson": f"eq.{lesson}"}).raise_for_status()
            if rows:
                c.post("/lessons_kb", json=rows, headers={"Prefer": "return=minimal"}).raise_for_status()
            print(f"{lesson}: {len(rows)} chunks")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "lessons")
