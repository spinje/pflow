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
from pflow.core.tts import strip_delivery_tags, synthesize, wav_duration

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
        # A safety-filtered 200 returns candidates: [] — must NOT be an IndexError. "hi" has no
        # tags to strip, so it is NOT retried; the message is the actionable no-audio one.
        _patch_post(monkeypatch, _FakeResponse(200, {"candidates": []}))
        with pytest.raises(TTSSynthesisError, match="no audio"):
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


def _no_audio_payload(finish_reason: str = "OTHER") -> dict[str, object]:
    """A 200 shaped like Gemini's live no-audio failure: a candidate with empty content."""
    return {"candidates": [{"content": {}, "finishReason": finish_reason, "index": 0}]}


class _RecordingPost:
    """A fake httpx.post that returns queued responses (or raises queued exceptions) in order and
    records the request body text of each call — so a test can assert call count AND that the
    stripped-tags retry sent the tag-free text."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.texts: list[str] = []

    def __call__(self, url: str, **kwargs: object) -> object:
        body = kwargs.get("json")
        assert isinstance(body, dict)
        self.texts.append(body["contents"][0]["parts"][0]["text"])
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestStrippedTagsRetry:
    """A 200-with-no-audio is retried ONCE with delivery tags stripped (whisper-bug recovery)."""

    def test_recovers_voice_by_stripping_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # First call (tagged text) returns no audio; the retry (tags stripped) returns audio.
        rec = _RecordingPost([_FakeResponse(200, _no_audio_payload()), _FakeResponse(200, _audio_payload(_PCM))])
        monkeypatch.setattr("pflow.core.tts.httpx.post", rec)
        wav = synthesize("[whispering playfully] hello there", model="m", voice="Kore")
        assert wav.startswith(b"RIFF")
        assert rec.texts == ["[whispering playfully] hello there", "hello there"]  # 2nd is tag-free

    def test_no_tags_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Nothing to strip → a single call, then the actionable no-audio error (no wasted retry).
        rec = _RecordingPost([_FakeResponse(200, _no_audio_payload())])
        monkeypatch.setattr("pflow.core.tts.httpx.post", rec)
        with pytest.raises(TTSSynthesisError, match="no audio"):
            synthesize("hello there", model="m", voice="Kore")
        assert len(rec.texts) == 1

    def test_network_error_is_not_retried_with_stripped_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A ConnectError is NOT a no-audio failure; stripping tags can't fix it, so no retry.
        rec = _RecordingPost([httpx.ConnectError("no route")])
        monkeypatch.setattr("pflow.core.tts.httpx.post", rec)
        with pytest.raises(TTSSynthesisError):
            synthesize("[whispers] hello there", model="m", voice="Kore")
        assert len(rec.texts) == 1

    def test_stripped_retry_also_no_audio_gives_actionable_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Both attempts return no audio → degrade with the actionable message naming the fix.
        rec = _RecordingPost([_FakeResponse(200, _no_audio_payload()), _FakeResponse(200, _no_audio_payload())])
        monkeypatch.setattr("pflow.core.tts.httpx.post", rec)
        with pytest.raises(TTSSynthesisError, match="delivery tag"):
            synthesize("[whispers] hello there", model="m", voice="Kore")
        assert len(rec.texts) == 2

    def test_no_audio_message_includes_finish_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_post(monkeypatch, _FakeResponse(200, _no_audio_payload("OTHER")))
        with pytest.raises(TTSSynthesisError, match="finishReason=OTHER"):
            synthesize("hello there", model="m", voice="Kore")


class TestWavDuration:
    def test_real_wav_reports_its_duration(self) -> None:
        # 24000 mono PCM16 frames at 24 kHz = exactly 1.0s (frames/rate is exact, no float fuzz).
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(24000)
            writer.writeframes(b"\x00\x00" * 24000)
        assert wav_duration(buffer.getvalue()) == 1.0

    def test_not_a_wav_is_zero(self) -> None:
        # Totality: the CLI sleeps for this value — a bad blob must never crash pacing.
        assert wav_duration(b"not a wav") == 0.0

    def test_empty_bytes_is_zero(self) -> None:
        assert wav_duration(b"") == 0.0


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
