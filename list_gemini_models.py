"""Diagnostic: list Gemini models your API key can actually call.

Run from project root:
    python list_gemini_models.py

Reads GEMINI_API_KEY from .env in the current directory. Prints every
model that supports generateContent — those are the ones you can plug
into GEMINI_MODEL in src/extract.py, or pass via the GEMINI_MODEL env var.

Use this when you get a 404 on a model name (Google retires older
versions periodically — `gemini-1.5-flash` was retired in 2025) or a
503 (model is overloaded — switch to a less in-demand sibling).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv


def main() -> None:
    # Load .env from the current working directory.
    load_dotenv()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY not set. Add it to .env in the project root, e.g.:\n"
            "    GEMINI_API_KEY=AIza..."
        )

    try:
        from google import genai
    except ImportError:
        raise SystemExit(
            "google-genai is not installed. Run: pip install google-genai"
        )

    client = genai.Client(api_key=api_key)
    print("Models supporting generateContent (use any of these as GEMINI_MODEL):\n")
    found_any = False
    for m in client.models.list():
        # SDK versions disagree on attribute name; check both.
        actions = (
            getattr(m, "supported_actions", None)
            or getattr(m, "supported_generation_methods", None)
            or []
        )
        if "generateContent" in actions:
            # `.name` usually comes back as "models/gemini-2.0-flash";
            # strip the prefix to get the form you paste into GEMINI_MODEL.
            short = m.name.split("/", 1)[1] if "/" in m.name else m.name
            display = getattr(m, "display_name", "") or ""
            print(f"  {short:40s}  {display}")
            found_any = True

    if not found_any:
        print("  (none found — your key may not have access, or the API surface changed)")


if __name__ == "__main__":
    main()
