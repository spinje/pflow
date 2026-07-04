"""Tests for the TTS synthesis seam (`pflow ui --say` narration).

The live Gemini call is mocked; these pin the parse/wrap logic and — crucially —
the totality contract: after the key check, every failure surfaces as
``TTSSynthesisError``, never a raw traceback.
"""

from __future__ import annotations

import base64
import io
import wave

import httpx
import pytest

from pflow.core.exceptions import MissingApiKeyError, TTSSynthesisError
from pflow.core.tts import strip_delivery_tags, synthesize

# A few PCM16 frames (signed 16-bit little-endian, mono): 3 samples.
_PCM = b"\x01\x00\x02\x00\x03\x00"


class _FakeResponse:
    def __init__(self, status_code: int, payload: object = None, text: str = "", raise_on_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._raise_on_json = raise_on_json

    def json(self) -> object:
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


def _audio_payload(pcm: bytes, mime: str = "audio/l16; rate=24000; channels=1") -> dict[str, object]:
    return {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"data": base64.b64encode(pcm).decode(), "mimeType": mime}}]}}
        ]
    }


@pytest.fixture(autouse=True)
def _gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give synthesize a key by default; the no-key test clears it explicitly."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: object | Exception) -> None:
    def fake_post(url: str, **kwargs: object) -> object:
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("pflow.core.tts.httpx.post", fake_post)


class TestSynthesizeHappyPath:
    def test_returns_playable_wav(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, _FakeResponse(200, _audio_payload(_PCM)))
        wav = synthesize("hello", model="gemini-3.1-flash-tts-preview", voice="Kore")
        assert wav.startswith(b"RIFF")
        with wave.open(io.BytesIO(wav), "rb") as reader:
            assert reader.getnchannels() == 1
            assert reader.getsampwidth() == 2
            assert reader.getframerate() == 24000
            assert reader.readframes(reader.getnframes()) == _PCM

    def test_strips_gemini_model_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, str] = {}

        def fake_post(url: str, **kwargs: object) -> object:
            seen["url"] = url
            return _FakeResponse(200, _audio_payload(_PCM))

        monkeypatch.setattr("pflow.core.tts.httpx.post", fake_post)
        synthesize("hi", model="gemini/gemini-3.1-flash-tts-preview", voice="Kore")
        assert seen["url"].endswith("/models/gemini-3.1-flash-tts-preview:generateContent")
        assert "gemini/" not in seen["url"].rsplit("/models/", 1)[1]

    def test_defensive_rate_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, _FakeResponse(200, _audio_payload(_PCM, mime="audio/l16; rate=48000; channels=1")))
        wav = synthesize("hi", model="m", voice="Kore")
        with wave.open(io.BytesIO(wav), "rb") as reader:
            assert reader.getframerate() == 48000

    def test_mime_without_rate_defaults_24000(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, _FakeResponse(200, _audio_payload(_PCM, mime="audio/l16")))
        wav = synthesize("hi", model="m", voice="Kore")
        with wave.open(io.BytesIO(wav), "rb") as reader:
            assert reader.getframerate() == 24000
            assert reader.getnchannels() == 1


class TestSynthesizeFailures:
    def test_non_200_raises_tts_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, _FakeResponse(429, text="rate limited"))
        with pytest.raises(TTSSynthesisError, match="429"):
            synthesize("hi", model="m", voice="Kore")

    def test_connect_error_raises_tts_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, httpx.ConnectError("no route"))
        with pytest.raises(TTSSynthesisError):
            synthesize("hi", model="m", voice="Kore")

    def test_timeout_raises_tts_error_with_actionable_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A too-long input times out; the message must hint at the real cause (length), not a raw repr.
        _patch_post(monkeypatch, httpx.ReadTimeout("read timed out"))
        with pytest.raises(TTSSynthesisError, match="timed out after 30s"):
            synthesize("hi", model="m", voice="Kore", timeout=30.0)

    def test_missing_inline_data_raises_tts_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, _FakeResponse(200, {"candidates": [{"content": {"parts": [{}]}}]}))
        with pytest.raises(TTSSynthesisError, match="no audio"):
            synthesize("hi", model="m", voice="Kore")

    def test_empty_candidates_raises_tts_error_not_index_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A safety-filtered 200 returns candidates: [] — must NOT be an IndexError.
        _patch_post(monkeypatch, _FakeResponse(200, {"candidates": []}))
        with pytest.raises(TTSSynthesisError, match="empty candidates"):
            synthesize("hi", model="m", voice="Kore")

    def test_non_json_200_body_raises_tts_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Totality: a 200 whose body doesn't parse must degrade to TTSSynthesisError.
        _patch_post(monkeypatch, _FakeResponse(200, raise_on_json=True))
        with pytest.raises(TTSSynthesisError):
            synthesize("hi", model="m", voice="Kore")

    def test_bad_base64_raises_tts_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"candidates": [{"content": {"parts": [{"inlineData": {"data": "!!!not-base64!!!"}}]}}]}
        _patch_post(monkeypatch, _FakeResponse(200, payload))
        with pytest.raises(TTSSynthesisError):
            synthesize("hi", model="m", voice="Kore")

    def test_no_key_raises_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(MissingApiKeyError, match="settings set-env"):
            synthesize("hi", model="m", voice="Kore")


class TestStripDeliveryTags:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("[excited] hi", "hi"),
            ("a [x] b [y] c", "a b c"),
            ("no tags", "no tags"),
            ("[only]", ""),
            ("[a][b] hi", "hi"),
        ],
    )
    def test_table(self, raw: str, expected: str) -> None:
        assert strip_delivery_tags(raw) == expected
