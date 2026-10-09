"""
Voice note → text, for SOPs written from a voice note (Action Program and up).
OpenAI Whisper when an OpenAI key is set, else Gemini; on a local machine with neither, a fixed sample
transcript so the whole flow can be tried. On a real deployment with no key, voice notes are switched off (503).
"""
import base64
import logging

import httpx
from fastapi import HTTPException

from .config import settings

log = logging.getLogger("hub")

OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
NO_KEY = "Voice notes need an OpenAI or Gemini key."

SAMPLE = ("When a new order comes in on WhatsApp, first I save the customer's name and number in the phone. "
          "Then I confirm what they want, the quantity and the delivery address, and I send them the price. "
          "Once they say yes, I ask for the advance on UPI and write it in the order book. "
          "Then the order goes for packing. We check it once against the order before it goes out. "
          "After delivery I send a thank-you message and ask if everything was fine.")

# Whisper reads the format from the file name, so the name must end in a known extension
EXTENSIONS = {"audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
              "audio/mp4": "m4a", "audio/m4a": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a", "audio/wav": "wav",
              "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac", "audio/x-flac": "flac", "audio/mpga": "mpga"}
GEMINI_MIME = {"audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "audio/x-m4a": "audio/m4a", "audio/x-flac": "audio/flac", "audio/mp3": "audio/mpeg"}


class TranscribeError(Exception):
    """The speech engine failed; the caller refunds the run and shows a plain message."""


def available() -> bool:
    return bool(settings.openai_api_key or settings.gemini_api_key or settings.local_dev)


def _file_name(filename: str, mime: str) -> str:
    ext = EXTENSIONS.get(mime, "webm")
    base = (filename or "voice-note").rsplit("/", 1)[-1][:80] or "voice-note"
    return base if base.lower().rsplit(".", 1)[-1] in set(EXTENSIONS.values()) | {"mp4", "mpeg"} else f"{base}.{ext}"


async def transcribe(data: bytes, filename: str, content_type: str) -> str:
    mime = (content_type or "").split(";")[0].strip().lower() or "audio/webm"
    try:
        if settings.openai_api_key:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(OPENAI_URL, headers={"authorization": f"Bearer {settings.openai_api_key}"},
                                      data={"model": "whisper-1"}, files={"file": (_file_name(filename, mime), data, mime)})
            if r.status_code != 200:
                raise TranscribeError(f"openai {r.status_code}: {r.text[:200]}")
            return str(r.json().get("text", "")).strip()
        if settings.gemini_api_key:
            model = settings.ai_model if settings.ai_model.startswith("gemini") else "gemini-2.5-flash"
            prompt = ("Transcribe this voice note word for word, in the language it is spoken (keep Hindi, Gujarati, Marathi or "
                      "Hinglish as spoken). Return only the transcript — no headings, no notes, no summary. "
                      "If there is no speech, return nothing.")
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": settings.gemini_api_key},
                                      json={"contents": [{"role": "user", "parts": [
                                          {"inlineData": {"mimeType": GEMINI_MIME.get(mime, mime), "data": base64.b64encode(data).decode()}},
                                          {"text": prompt}]}],
                                          "generationConfig": {"maxOutputTokens": 8192, "temperature": 0}})
            if r.status_code != 200:
                raise TranscribeError(f"gemini {r.status_code}: {r.text[:200]}")
            parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts).strip()
    except httpx.HTTPError as e:
        raise TranscribeError("The speech engine could not be reached") from e
    if settings.local_dev:
        return SAMPLE
    raise HTTPException(503, NO_KEY)
