"""Load only the Groq credential; do not execute or expand dotenv contents."""
import os
from pathlib import Path
import re

from fastapi import HTTPException

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def groq_key():
    value = os.environ.get("GROQ_API_KEY", "").strip()
    if not value and ENV_PATH.exists():
        entries = []
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, candidate = line.partition("=")
            if separator and name.strip() == "GROQ_API_KEY":
                candidate = candidate.strip()
                if candidate[:1] in ("'", '"'):
                    if len(candidate) < 2 or candidate[-1] != candidate[0]:
                        raise HTTPException(503, "Malformed GROQ_API_KEY quoting in .env; no hosted request attempted")
                    candidate = candidate[1:-1]
                else:
                    candidate = candidate.split("#", 1)[0].strip()
                entries.append(candidate)
        if len(entries) > 1:
            raise HTTPException(503, "Duplicate GROQ_API_KEY assignments in .env; no hosted request attempted")
        value = entries[0] if entries else ""
    if value and not re.fullmatch(r"gsk_[A-Za-z0-9_-]+", value):
        raise HTTPException(503, "GROQ_API_KEY has an invalid prefix or whitespace; no hosted request attempted")
    return value
