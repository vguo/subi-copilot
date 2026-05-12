"""Transcribe audio handoffs to text using faster-whisper (local CPU inference).

Local-only by design:
- No API key required.
- Audio never leaves the machine.
- Per-shift cost is $0 once the model is downloaded.

faster-whisper is used over the reference openai-whisper because it's ~4x
faster on CPU (via CTranslate2) and avoids the ffmpeg install pain that bites
Windows users with the reference implementation.

Model size recommendations for clinical handoffs:
    - 'tiny'   (~75MB):  too inaccurate for medication names
    - 'base'   (~150MB): borderline; misses uncommon drug names
    - 'small'  (~470MB): solid default for clean voice memos
    - 'medium' (~1.5GB): worth it for messy real-shift recordings
    - 'large-v3' (~3GB): best accuracy, slow on CPU

The model auto-downloads from Hugging Face on first use and is cached locally
(typically under %USERPROFILE%\\.cache\\huggingface\\hub).
"""

from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel

DEFAULT_MODEL_SIZE = "small"

# Biases Whisper's decoder toward medical vocabulary. Without this, drug names
# get mangled into common English words ("furosemide" -> "for a samide",
# "Lasix" -> "lay six") and lab terms get phonetic mush. The string isn't
# transcribed — it's only used to nudge token probabilities.
HANDOFF_INITIAL_PROMPT = (
    "Internal medicine handoff. Drugs: furosemide, Lasix, lisinopril, carvedilol, "
    "prednisone, azithromycin, ceftriaxone, doxycycline, vancomycin, heparin, "
    "apixaban, pantoprazole, metoprolol, atorvastatin, aspirin, spironolactone, "
    "hydrochlorothiazide, losartan, cefazolin, lactulose, insulin, glargine, "
    "lispro, albuterol, duonebs. Labs: BMP, CBC, troponin, BNP, lactate, "
    "hemoglobin, creatinine, potassium, sodium, magnesium, glucose, INR, lactate, "
    "procalcitonin. Locations: bed, east, west, north, south, stepdown, telemetry. "
    "Vitals: heart rate, blood pressure, oxygen saturation, respiratory rate."
)

# Module-level cache so repeated calls within one process don't reload the
# model from disk. Streamlit reruns the script on every interaction, so this
# cache is per-Python-process; Streamlit's @st.cache_resource handles the
# longer-lived caching in app.py.
_MODEL_CACHE: dict[str, WhisperModel] = {}


def _get_model(model_size: str = DEFAULT_MODEL_SIZE) -> WhisperModel:
    """Lazily load and cache a Whisper model by size."""
    if model_size not in _MODEL_CACHE:
        # int8 quantization on CPU is the right default: ~half the memory,
        # ~2x speed, negligible accuracy loss for transcription.
        _MODEL_CACHE[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8"
        )
    return _MODEL_CACHE[model_size]


def transcribe(
    audio_path: Path | str,
    *,
    model_size: str = DEFAULT_MODEL_SIZE,
) -> str:
    """Transcribe an audio file to a plain-text transcript.

    Args:
        audio_path: Path to audio file (.m4a, .mp3, .wav, .ogg, .mp4 etc).
        model_size: Whisper model. See module docstring for tradeoffs.

    Returns:
        Plain text transcript. Whisper's segments are joined with single spaces.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = _get_model(model_size)

    # vad_filter=True drops long silences; helpful for ambient handoff
    # recordings where the speaker pauses.
    # initial_prompt biases the decoder toward medical vocabulary.
    segments, _info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        initial_prompt=HANDOFF_INITIAL_PROMPT,
    )

    # segments is a generator — we materialize it here.
    return " ".join(seg.text.strip() for seg in segments)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m src.transcribe <audio_file>")
        sys.exit(1)
    print(transcribe(sys.argv[1]))
