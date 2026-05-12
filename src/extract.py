"""Extract structured handoff data from a transcript.

Two LLM providers are supported behind a single interface:

    extract_handoff_cached(transcript, provider="claude")  # paid, ~$0.04/patient
    extract_handoff_cached(transcript, provider="gemini")  # free tier via AI Studio

Both producers go through the same Pydantic schema. The cache key includes
the resolved model string, so switching providers cleanly gets its own cache
namespace — no manual invalidation needed.

Implementation notes:
- Claude uses **tool-use** to enforce the schema (the model fills a tool's
  `input_schema`, which IS the Pydantic JSON schema).
- Gemini uses **`response_schema` + `response_mime_type="application/json"`**
  to enforce the schema (Gemini's native structured output mode).
- Both paths return a validated `HandoffExtraction`. Callers don't need to
  know which provider was used (except for cost / latency considerations).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from anthropic import Anthropic
from dotenv import load_dotenv

from .schema import HandoffExtraction

# Load API keys from .env at import time. The Anthropic and google-genai
# clients both read keys from os.environ, so this must happen before any
# client is constructed.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
EXTRACTION_PROMPT_PATH = PROMPTS_DIR / "extraction.md"
CACHE_DIR = PROJECT_ROOT / ".cache" / "extractions"

# Provider type — keep as Literal for autocomplete / type-checking.
LLMProvider = Literal["claude", "gemini"]

# Default per-provider model strings. Both are picked to be the right "tier
# for extraction" on each platform: fast, cheap, clean structured output.
# To change models, edit here — the cache key includes the model string so
# changes auto-invalidate the cache.
CLAUDE_MODEL = "claude-sonnet-4-5"
# NOTE: gemini-1.5-flash was retired by Google in 2025. Use 2.x or later.
# If this errors with "model not found", run the diagnostic in DEPLOY.md
# (or src/list_gemini_models.py) to enumerate what your API key can call.
GEMINI_MODEL = "gemini-2.5-flash"


def _load_prompt() -> str:
    return EXTRACTION_PROMPT_PATH.read_text(encoding="utf-8")


def _model_for_provider(provider: LLMProvider) -> str:
    """Resolve provider -> concrete model string used by that provider."""
    if provider == "claude":
        return CLAUDE_MODEL
    if provider == "gemini":
        return GEMINI_MODEL
    raise ValueError(f"Unknown provider: {provider!r}")


def _cache_key(transcript: str, provider: LLMProvider) -> str:
    """Compute a cache key that invalidates when any input to extraction changes.

    Hashes the model string + the prompt + the JSON schema + the transcript.
    Switching providers changes the model string, which changes the key, so
    the two providers cache independently with zero extra logic.
    """
    model = _model_for_provider(provider)
    schema_str = json.dumps(HandoffExtraction.model_json_schema(), sort_keys=True)
    prompt = _load_prompt()
    blob = f"{model}\x1f{schema_str}\x1f{prompt}\x1f{transcript}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def is_cached(transcript: str, *, provider: LLMProvider = "claude") -> bool:
    """Check whether this transcript already has a cached extraction.

    Used by UI code to show "cached / free" vs "fresh / paid" feedback
    *before* extraction runs, so the user can decide. The provider matters
    because each provider has its own cache namespace via the model string.
    """
    return (CACHE_DIR / f"{_cache_key(transcript, provider)}.json").exists()


def extract_handoff_cached(
    transcript: str,
    *,
    provider: LLMProvider = "claude",
    client: Anthropic | None = None,
    force_fresh: bool = False,
) -> HandoffExtraction:
    """Same as extract_handoff, but caches the result to .cache/extractions/.

    First call for a given (transcript, provider) hits the API and writes
    JSON to disk. Subsequent calls with the same inputs read from disk and
    cost $0. Cache is auto-invalidated when the prompt, schema, or model
    string changes.

    Args:
        transcript: The handoff transcript text.
        provider: Which LLM to call. Defaults to "claude".
        client: Optional Anthropic client (for testing/mocking; Claude only).
        force_fresh: If True, bypass the cache and re-extract from the API.
    """
    key = _cache_key(transcript, provider)
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists() and not force_fresh:
        return HandoffExtraction.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )

    extraction = extract_handoff(transcript, provider=provider, client=client)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
    return extraction


def extract_handoff(
    transcript: str,
    *,
    provider: LLMProvider = "claude",
    client: Anthropic | None = None,
) -> HandoffExtraction:
    """Extract structured Patient list from a handoff transcript.

    Args:
        transcript: Raw text of the handoff (from ASR or pasted).
        provider: Which LLM to call. Defaults to "claude".
        client: Optional pre-built Anthropic client (Claude only — ignored
            for Gemini, which uses the google-genai client internally).

    Returns:
        Validated HandoffExtraction.

    Raises:
        RuntimeError: if the provider's API key is not set.
        ValueError: if the model output failed validation.
    """
    if provider == "claude":
        return _extract_via_claude(transcript, client=client)
    if provider == "gemini":
        return _extract_via_gemini(transcript)
    raise ValueError(f"Unknown provider: {provider!r}")


# --- Claude (Anthropic tool-use) -----------------------------------------

def _build_claude_tool_schema() -> dict:
    """Convert the Pydantic schema into an Anthropic tool definition."""
    return {
        "name": "record_handoff",
        "description": "Record the structured handoff extraction for one or more patients.",
        "input_schema": HandoffExtraction.model_json_schema(),
    }


def _extract_via_claude(
    transcript: str,
    *,
    client: Anthropic | None = None,
) -> HandoffExtraction:
    """Extract via Anthropic Claude using tool-use for structured output."""
    client = client or Anthropic()
    system_prompt = _load_prompt()
    tool = _build_claude_tool_schema()

    response = client.messages.create(
        model=CLAUDE_MODEL,
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
            "Claude did not call the record_handoff tool. "
            f"Response content: {response.content!r}"
        )

    return HandoffExtraction.model_validate(tool_use_block.input)


# --- Gemini (Google AI Studio response_schema) ----------------------------

def _extract_via_gemini(transcript: str) -> HandoffExtraction:
    """Extract via Google Gemini using response_schema for structured output.

    Free tier limits (AI Studio): 15 RPM, ~1500 requests/day on Flash. Plenty
    for personal use. Note that on the free tier, Google may use prompts for
    product improvement — synthetic-data-only stance applies.
    """
    # Lazy import so users who never select Gemini don't pay the import cost
    # and don't fail on app start if google-genai isn't installed.
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise RuntimeError(
            "google-genai is not installed. Run: pip install google-genai"
        ) from e

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Get a free key at "
            "https://aistudio.google.com/apikey and add it to .env (locally) "
            "or st.secrets (Streamlit Cloud)."
        )

    client = genai.Client(api_key=api_key)
    system_prompt = _load_prompt()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=transcript,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=HandoffExtraction,
            temperature=0.0,  # deterministic extraction
        ),
    )

    # Prefer the SDK's parsed response when available — it handles edge cases
    # like enum normalization. Fall back to manual parsing if the SDK didn't
    # populate `.parsed` (some response shapes leave it None).
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, HandoffExtraction):
        return parsed
    if parsed is not None:
        # SDK gave us a dict; coerce via Pydantic
        return HandoffExtraction.model_validate(parsed)

    raw_text = getattr(response, "text", None)
    if not raw_text:
        raise ValueError(
            "Gemini returned no parsed object and no text. Response: "
            f"{response!r}"
        )
    return HandoffExtraction.model_validate_json(raw_text)


# --- CLI entry point ------------------------------------------------------

if __name__ == "__main__":
    # Quick smoke test: read a handoff from stdin or a file arg, print the JSON.
    # Provider defaults to claude; override with --provider gemini.
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Extract a handoff transcript.")
    parser.add_argument("path", nargs="?", help="Path to transcript file (else stdin).")
    parser.add_argument(
        "--provider",
        choices=["claude", "gemini"],
        default="claude",
        help="Which LLM to call.",
    )
    args = parser.parse_args()

    if args.path:
        text = Path(args.path).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    result = extract_handoff(text, provider=args.provider)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
