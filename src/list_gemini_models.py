"""Diagnostic: list Gemini models that your API key can actually call.

Run when you get a 404 on a model name (Google retires older versions
periodically — `gemini-1.5-flash` was retired in 2025, etc.).

Usage:
    python -m src.list_gemini_models

Reads GEMINI_API_KEY from .env (via the load_dotenv() in extract.py).
Prints every model that supports generateContent — those are the ones you
can plug into GEMINI_MODEL in src/extract.py.
"""

from __future__ import annotations

import os

# Triggers load_dotenv() and brings GEMINI_API_KEY into os.environ
from . import extract  # noqa: F401


def main() -> None:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY not set. Add it to .env or export it before running."
        )

    client = genai.Client(api_key=api_key)
    print("Models supporting generateContent (use any of these as GEMINI_MODEL):\n")
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or getattr(
            m, "supported_generation_methods", []
        )
        if "generateContent" in actions:
            # The .name often comes back as "models/gemini-2.5-flash";
            # strip the prefix for the form you paste into GEMINI_MODEL.
            short = m.name.split("/", 1)[1] if "/" in m.name else m.name
            display = getattr(m, "display_name", "") or ""
            print(f"  {short:40s}  {display}")


if __name__ == "__main__":
    main()
