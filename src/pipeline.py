"""End-to-end orchestration: audio/text → extraction → rendered HTML.

This is the single entry point both the CLI and the Streamlit app use, so
business logic lives in one place. Keeping pipeline thin and presentation-free
means a future Discord bot, FastAPI server, or batch script can all reuse it
without re-implementing the steps.

Two entry points:
    process_text(transcript)         -> (extraction, html)
    process_audio(audio_path)        -> (transcript, extraction, html)
"""

from __future__ import annotations

from pathlib import Path

from .extract import extract_handoff_cached
from .render import render_sheet
from .schema import HandoffExtraction


def process_text(transcript: str) -> tuple[HandoffExtraction, str]:
    """Run extraction + rendering on an existing transcript.

    Returns:
        (HandoffExtraction, rendered HTML string)
    """
    extraction = extract_handoff_cached(transcript)
    html_out = render_sheet(extraction)
    return extraction, html_out


def process_audio(
    audio_path: Path | str,
    *,
    model_size: str = "small",
) -> tuple[str, HandoffExtraction, str]:
    """Transcribe audio, then run extraction + rendering.

    The whisper import is lazy so callers using only text input don't pay
    the import cost (faster-whisper pulls in ctranslate2, ~30s import on
    first load).

    Returns:
        (transcript, HandoffExtraction, rendered HTML string)
    """
    from .transcribe import transcribe  # lazy import

    transcript = transcribe(audio_path, model_size=model_size)
    extraction, html_out = process_text(transcript)
    return transcript, extraction, html_out
