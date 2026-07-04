"""Text-to-speech synthesis for `pflow ui --say` narration.

A sibling of ``llm_client.py``, NOT part of it: the dependency surface (raw
``httpx`` vs LiteLLM), the interface (``synthesize`` returns WAV bytes, not an
``AdapterResponse``), and the failure model are all different. Keeping it its own
module keeps each seam small.

The module is a **deep module behind a one-field interface**: the agent's entire
surface is the sentence passed to ``--say``. Provider, voice, model, URL shape,
PCM parameters, and the WAV wrapper all live here; swapping to another TTS
provider is a change inside :func:`synthesize` with zero agent-command change.

Failure model (load-bearing — see the plan's "never-raises seam"): after the API
key check, :func:`synthesize` is **total**. A missing key raises
:class:`MissingApiKeyError`; every other failure (network, non-200, a 200 with an
empty ``candidates`` list from a safety filter, malformed base64, a reshaped
response body, degenerate audio parameters) surfaces as
:class:`TTSSynthesisError` — never a raw traceback. The CLI's ``--say`` path
catches both and degrades to caption-only, so a synthesis failure is a report
note, not an aborted point.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import wave

import httpx

from pflow.core.exceptions import MissingApiKeyError, TTSSynthesisError
from pflow.core.llm_config import PROVIDER_ENV_VARS

# Gemini generateContent surface (live-verified 2026-07-04, returns 200 with base64 PCM16 audio).
_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# PCM defaults when the response mimeType omits them — Gemini returns
# "audio/l16; rate=24000; channels=1" today, but parsing rate/channels defensively
# guards against a silent pitch-shift if Google changes the rate.
_DEFAULT_RATE = 24000
_DEFAULT_CHANNELS = 1
_PCM16_SAMPLE_WIDTH = 2  # bytes per sample; the response is signed 16-bit little-endian PCM

_DELIVERY_TAG_RE = re.compile(r"\[[^\]]*\]")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_delivery_tags(text: str) -> str:
    """Return the spoken caption: the text with ``[delivery]`` tags removed.

    Gemini takes delivery direction inline as bracketed tags (``[excited]``,
    ``[whispers]``, …) that are consumed, not spoken. Stripping them makes the
    caption equal the spoken *words* while the tags shape only *how* they sound.
    Collapses the whitespace the removed tags leave behind.
    """
    stripped = _DELIVERY_TAG_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def synthesize(text: str, *, model: str, voice: str, timeout: float = 30.0) -> bytes:
    """Synthesize ``text`` (delivery tags included) to WAV bytes via Gemini TTS.

    Args:
        text: The raw ``--say`` text, tags included — Gemini reads the tags.
        model: The TTS model id; a leading ``gemini/`` (LiteLLM settings
            convention) is stripped before URL interpolation.
        voice: The prebuilt voice name (e.g. ``"Kore"``).
        timeout: httpx request timeout in seconds.

    Returns:
        WAV bytes (PCM16 wrapped with stdlib ``wave``), playable by a browser.

    Raises:
        MissingApiKeyError: no Gemini key in the environment.
        TTSSynthesisError: any other failure — this function is total after the
            key check.
    """
    key = _gemini_api_key()
    if key is None:
        raise MissingApiKeyError(
            "No Gemini API key found for TTS narration. Set GEMINI_API_KEY (or "
            "GOOGLE_API_KEY) in your environment, or run "
            "'pflow settings set-env GEMINI_API_KEY <value>'.",
            model=model,
        )

    model_id = model.removeprefix("gemini/")
    url = f"{_GEMINI_MODELS_URL}/{model_id}:generateContent"
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }

    # TOTALITY (load-bearing): everything after the key check is wrapped. A
    # non-200, a 200 with empty candidates (safety filter), malformed base64, a
    # reshaped body (KeyError/IndexError/TypeError/binascii.Error), or degenerate
    # audio params (wave.Error) must all surface as TTSSynthesisError. The
    # explicit TTSSynthesisErrors below re-raise unchanged (excluded from the
    # wide catch); nothing else escapes as a raw traceback.
    try:
        response = httpx.post(url, json=body, headers={"x-goog-api-key": key}, timeout=timeout)
        if response.status_code != 200:
            raise TTSSynthesisError(f"Gemini TTS returned HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        data_b64, mime = _extract_audio(payload)
        pcm = base64.b64decode(data_b64)
        rate, channels = _parse_pcm_params(mime)
        return _wrap_wav(pcm, rate=rate, channels=channels)
    except (MissingApiKeyError, TTSSynthesisError):
        raise
    except httpx.TimeoutException as exc:
        # A distinct, actionable message: generation scales with text length (measured ~0.7-0.9x
        # realtime for short lines, disproportionately slower near the char cap), so a timeout most
        # often means the text is long — a different remedy than a network error.
        raise TTSSynthesisError(
            f"TTS synthesis timed out after {timeout:g}s — the text may be too long to narrate."
        ) from exc
    except Exception as exc:
        raise TTSSynthesisError(f"TTS synthesis failed: {exc}") from exc


def _gemini_api_key() -> str | None:
    """First non-empty Gemini key from the environment (canonical-first).

    ``PROVIDER_ENV_VARS["gemini"]`` carries the registry's canonical-first order
    (``GEMINI_API_KEY`` then ``GOOGLE_API_KEY``). The CLI injects settings-stored
    keys into ``os.environ`` before calling this, so reading the environment
    covers both sources.
    """
    # `.get("gemini", [])` mirrors llm_config._has_provider_key — a robust no-key degrade rather than a
    # raw KeyError (this runs BEFORE synthesize()'s totality wrapper, so it must not throw unexpectedly).
    for var in PROVIDER_ENV_VARS.get("gemini", []):
        value = os.environ.get(var, "").strip()
        if value:
            return value
    return None


def _extract_audio(payload: object) -> tuple[str, str]:
    """Pull the base64 audio + mimeType out of a generateContent response.

    Raises TTSSynthesisError (not IndexError/KeyError) on an empty ``candidates``
    list (safety-filtered 200) or any missing key.
    """
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not candidates:
        raise TTSSynthesisError(f"no audio in response (empty candidates): {_preview(payload)}")
    try:
        inline = candidates[0]["content"]["parts"][0]["inlineData"]
        data = inline["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TTSSynthesisError(f"no audio in response (missing inlineData): {_preview(payload)}") from exc
    if not isinstance(data, str):
        raise TTSSynthesisError(f"no audio in response (non-string data): {_preview(payload)}")
    mime = inline.get("mimeType", "") if isinstance(inline, dict) else ""
    return data, mime if isinstance(mime, str) else ""


def _parse_pcm_params(mime: str) -> tuple[int, int]:
    """Parse ``rate=`` / ``channels=`` from the mimeType, defaulting 24000/1."""
    rate_match = re.search(r"rate=(\d+)", mime)
    channels_match = re.search(r"channels=(\d+)", mime)
    rate = int(rate_match.group(1)) if rate_match else _DEFAULT_RATE
    channels = int(channels_match.group(1)) if channels_match else _DEFAULT_CHANNELS
    return rate, channels


def _wrap_wav(pcm: bytes, *, rate: int, channels: int) -> bytes:
    """Wrap raw PCM16 bytes in a WAV container (stdlib ``wave``)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(_PCM16_SAMPLE_WIDTH)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _preview(payload: object) -> str:
    """First ~200 chars of a JSON dump, for a TTSSynthesisError message."""
    try:
        return json.dumps(payload)[:200]
    except (TypeError, ValueError):
        return str(payload)[:200]
