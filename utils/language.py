"""Language resolution and report-language rules.

This module is the single source of truth for *what language the meeting
report should be written in*. It is deliberately tiny and dependency-free so
both the live pipeline (sessions.session) and the offline re-processor
(tools.retranscribe) can share the exact same logic.

Two responsibilities:

  * resolve_report_language(requested, detected): decide the effective report
    language. An explicit user choice (e.g. "en"/"bn") always wins; otherwise
    we follow the language Whisper actually detected from the audio.
  * language_rule_for(code): turn a language code into a precise instruction
    for the LLM. NOTHING is hardcoded to Bengali — the rule is built from the
    resolved language so an English meeting yields an English report, a Hindi
    meeting a Hindi report, and so on.
"""

from __future__ import annotations

from typing import Optional

# ISO 639-1 (Whisper-style) codes -> human-readable language names used in the
# LLM instruction. This list is not exhaustive; any code not present falls back
# to a generic "write in the transcript's language" instruction, so unknown
# languages still produce a correctly-matched report.
LANGUAGE_NAMES: dict[str, str] = {
    "bn": "Bengali (Bangla)",
    "en": "English",
    "hi": "Hindi",
    "ur": "Urdu",
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "it": "Italian",
    "nl": "Dutch",
    "tr": "Turkish",
    "id": "Indonesian",
    "ms": "Malay",
    "ta": "Tamil",
    "te": "Telugu",
    "ne": "Nepali",
    "si": "Sinhala",
    "th": "Thai",
    "vi": "Vietnamese",
    "fa": "Persian",
    "pl": "Polish",
    "uk": "Ukrainian",
    "ro": "Romanian",
    "sv": "Swedish",
}

# Values that mean "no explicit choice — let the detected language decide".
_AUTO_VALUES = {"", "auto", "none", "others", "other"}

# Policy remap: some detected languages are intentionally reported in a
# DIFFERENT language. Per request, a Hindi transcript produces a Bangla report
# (the reader uses Bangla, not Devanagari) — the LLM translates the summary
# from Hindi into Bangla. Every OTHER language still matches the transcript;
# only the pairs listed here are remapped. Add more pairs here if needed.
REPORT_LANGUAGE_REMAP: dict[str, str] = {
    "hi": "bn",   # Hindi transcript -> Bangla report
}

# Cloud Whisper APIs (Groq/OpenAI) often report the full language NAME
# ("english", "bengali") instead of the ISO code that faster-whisper returns
# ("en", "bn"). Map the common names back to codes so the rest of the pipeline
# stays code-based.
_NAME_TO_CODE = {
    "english": "en", "bengali": "bn", "bangla": "bn", "hindi": "hi",
    "urdu": "ur", "arabic": "ar", "spanish": "es", "french": "fr",
    "german": "de", "portuguese": "pt", "russian": "ru", "chinese": "zh",
    "japanese": "ja", "korean": "ko", "italian": "it", "dutch": "nl",
    "turkish": "tr", "indonesian": "id", "malay": "ms", "tamil": "ta",
    "telugu": "te", "nepali": "ne", "sinhala": "si", "thai": "th",
    "vietnamese": "vi", "persian": "fa", "polish": "pl", "ukrainian": "uk",
    "romanian": "ro", "swedish": "sv",
}


def normalize_language_code(value: Optional[str]) -> Optional[str]:
    """Normalise a detected language to an ISO 639-1 code (or None).

    Accepts either an ISO code ("en") or a full name ("english") and returns
    the code. Unknown values are returned lower-cased and untouched so a
    correct-but-unlisted code still flows through.
    """
    v = (value or "").strip().lower()
    if not v:
        return None
    if v in LANGUAGE_NAMES:        # already a known ISO code
        return v
    return _NAME_TO_CODE.get(v, v)


def display_name(code: Optional[str]) -> str:
    """Return a friendly language name for a code (or the code itself)."""
    c = (code or "").strip().lower()
    return LANGUAGE_NAMES.get(c, c or "unknown")


def resolve_report_language(
    requested: Optional[str], detected: Optional[str]
) -> str:
    """Decide the effective report language.

    Precedence:
      1. "mixed"            -> preserve the mixed-language style (handled in
                               the rule below); detection still informs the
                               dominant language at write time.
      2. an explicit, concrete user choice ("en", "bn", or any real code)
                            -> honour it; the user deliberately overrode auto.
      3. otherwise ("auto"/empty/None)
                            -> use the language Whisper detected.
      4. if nothing was detected either -> "auto" (let the LLM match the text).

    Finally, REPORT_LANGUAGE_REMAP is applied (e.g. Hindi -> Bangla), so the
    report can intentionally differ from the transcript for specific languages.
    """
    req = (requested or "").strip().lower()
    det = normalize_language_code(detected) or ""

    if req == "mixed":
        result = "mixed"
    elif req and req not in _AUTO_VALUES:
        result = req  # explicit user override (e.g. forced English/Bangla)
    else:
        result = det or "auto"  # follow what Whisper detected

    # Policy remap (e.g. a Hindi transcript is reported in Bangla).
    return REPORT_LANGUAGE_REMAP.get(result, result)


def language_rule_for(code: Optional[str]) -> str:
    """Build the LLM language instruction for a resolved language code.

    No language is hardcoded as a default: "auto" tells the model to match the
    transcript, a known code names the language explicitly, and an unknown code
    still pins the output to the transcript's language.
    """
    c = (code or "").strip().lower()

    if c in _AUTO_VALUES:
        return (
            "Write ALL values in the SAME language as the transcript below. "
            "Infer that language from the transcript text itself and match it "
            "exactly. Do NOT translate the content into any other language."
        )

    if c == "mixed":
        return (
            "Write the values in the transcript's dominant language, but keep "
            "any words or phrases that were spoken in another language (for "
            "example English technical or business terms such as 'sales', "
            "'budget', 'KPI') exactly as they were spoken, without translating "
            "them."
        )

    name = LANGUAGE_NAMES.get(c)
    if name:
        return f"Write ALL values in {name}."

    return (
        f"Write ALL values in the language of the transcript (detected "
        f"language code: '{c}'). Do NOT translate the content into any other "
        f"language."
    )