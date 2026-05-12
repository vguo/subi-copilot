"""Extract structured handoff data from a transcript.

Uses Anthropic tool-use to enforce the Pydantic schema. Tool-use is more
reliable than asking for JSON in prose: the model fills out a schema rather
than improvising delimiters, so we get clean structured output every time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from .schema import HandoffExtraction

# Load ANTHROPIC_API_KEY from .env at import time. The Anthropic SDK reads
# the key from os.environ, so this must happen before client construction.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
EXTRACTION_PROMPT_PATH = PROMPTS_DIR / "extraction.md"
CACHE_DIR = PROJECT_ROOT / ".cache" / "extractions"

# Sonnet-class is the right tier for extraction per the plan doc:
# fast, cheap, clean structured output. Reserve heavier models for watch-outs.
EXTRACTION_MODEL = "claude-sonnet-4-5"


def _load_prompt() -> str:
    return EXTRACTION_PROMPT_PATH.read_text()


def _build_tool_schema() -> dict:
    """Convert the Pydantic schema into an Anthropic tool definition."""
    return {
        "name": "record_handoff",
        "description": "Record the structured handoff extraction for one or more patients.",
        "input_schema": HandoffExtraction.model_json_schema(),
    }


def _cache_key(transcript: str) -> str:
    """Compute a cache key that invalidates when any input to extraction changes.

    Hashes the model name + the prompt + the JSON schema + the transcript.
    Changing the prompt, the schema, the model, or the transcript all bust
    the cache automatically. No manual invalidation needed.
    """
    schema_str = json.dumps(HandoffExtraction.model_json_schema(), sort_keys=True)
    prompt = _load_prompt()
    blob = f"{EXTRACTION_MODEL}\x1f{schema_str}\x1f{prompt}\x1f{transcript}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def is_cached(transcript: str) -> bool:
    """Check whether this transcript already has a cached extraction.

    Used by UI code to show "cached / free" vs "fresh / paid" feedback
    *before* extraction runs, so the user can decide.
    """
    return (CACHE_DIR / f"{_cache_key(transcript)}.json").exists()


def extract_handoff_cached(
    transcript: str,
    *,
    client: Anthropic | None = None,
    force_fresh: bool = False,
) -> HandoffExtraction:
    """Same as extract_handoff, but caches the result to .cache/extractions/.

    First call for a given transcript hits the API and writes JSON to disk.
    Subsequent calls with the same inputs read from disk and cost $0.
    Cache is auto-invalidated when the prompt, schema, or model changes.

    Args:
        transcript: The handoff transcript text.
        client: Optional Anthropic client (for testing/mocking).
        force_fresh: If True, bypass the cache and re-extract from the API.
            Useful for retrying a bad extraction without editing the transcript.
    """
    key = _cache_key(transcript)
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists() and not force_fresh:
        return HandoffExtraction.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )

    extraction = extract_handoff(transcript, client=client)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
    return extraction


def extract_handoff(transcript: str, *, client: Anthropic | None = None) -> HandoffExtraction:
    """Extract structured Patient list from a handoff transcript.

    Args:
        transcript: Raw text of the handoff (from ASR or pasted).
        client: Optional pre-built Anthropic client (useful for testing/mocking).

    Returns:
        Validated HandoffExtraction.

    Raises:
        ValueError: if the model did not call the tool, or its output failed validation.
    """
    client = client or Anthropic()
    system_prompt = _load_prompt()
    tool = _build_tool_schema()

    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8000,
        system=system_prompt,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_handoff"},
        messages=[{"role": "user", "content": transcript}],
    )

    tool_use_block = next(
        (block for block in response.content if block.type == "tool_use"),
        None,
    )
    if tool_use_block is None:
        raise ValueError(
            "Extraction model did not call the record_handoff tool. "
            f"Response content: {response.content!r}"
        )

    return HandoffExtraction.model_validate(tool_use_block.input)


if __name__ == "__main__":
    # Quick smoke test: read a handoff from stdin or a file arg, print the JSON.
    import sys

    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text()
    else:
        text = sys.stdin.read()

    result = extract_handoff(text)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
