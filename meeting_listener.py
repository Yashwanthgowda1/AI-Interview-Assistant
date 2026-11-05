"""
meeting_listener.py — Real-time loopback audio capture + transcription.
Transcribes audio locally with faster-whisper every CHUNK_SECONDS seconds and
calls on_text().
"""
from __future__ import annotations
import logging, threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE   = 16000
CHUNK_SECONDS = 5   # transcribe every N seconds of audio

_whisper_model = None
_whisper_model_lock = threading.Lock()
_transcription_lock = threading.Lock()


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_model_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel

                logger.info("Loading local faster-whisper base model")
                _whisper_model = WhisperModel(
                    "base",
                    device="cpu",
                    compute_type="int8",
                )
    return _whisper_model


def _transcribe_chunk(samples, language: str) -> str:
    import numpy as np

    peak = float(np.max(np.abs(samples)))
    if peak < 0.002:
        return ""

    gain = min(0.8 / peak, 6.0)
    samples = (samples * gain).clip(-1.0, 1.0).astype(np.float32)
    model = _get_whisper_model()
    language_code = language.split("-", 1)[0].strip() or None

    # Audio chunks are flushed on separate threads, so serialize model inference.
    with _transcription_lock:
        segments, _ = model.transcribe(
            samples,
            language=language_code,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def _capture_pyaudiowpatch(stop_event, on_chunk):
    import pyaudiowpatch as pyaudio
    import numpy as np

    p = pyaudio.PyAudio()
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        p.terminate()
        raise RuntimeError("WASAPI host API not available")

    default_spk = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

    device = None
    for lb in p.get_loopback_device_info_generator():
        if default_spk["name"] in lb["name"]:
            device = lb
            break
    if device is None:
        for lb in p.get_loopback_device_info_generator():
            device = lb
            break
    if device is None:
        p.terminate()
        raise RuntimeError("No WASAPI loopback device found")

    native_rate = int(device["defaultSampleRate"])
    channels    = max(1, int(device.get("maxInputChannels") or
                             device.get("maxOutputChannels") or 2))
    read_frames = native_rate  # read 1 second at a time

    logger.info("WASAPI loopback: '%s'  %d Hz  %d ch", device["name"], native_rate, channels)

    stream = p.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=native_rate,
        input=True,
        input_device_index=device["index"],
        frames_per_buffer=1024,
    )
    try:
        while not stop_event.is_set():
            raw = stream.read(read_frames, exception_on_overflow=False)
            pcm = np.frombuffer(raw, dtype=np.int16).copy()
            if channels > 1:
                pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
            if native_rate != SAMPLE_RATE:
                n_new = int(len(pcm) * SAMPLE_RATE / native_rate)
                x_old = np.arange(len(pcm), dtype=np.float32)
                x_new = np.linspace(0, len(pcm) - 1, n_new, dtype=np.float32)
                pcm   = np.interp(x_new, x_old, pcm.astype(np.float32)).astype(np.int16)
            on_chunk(pcm.astype(np.float32) / 32767.0)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def _capture_soundcard(stop_event, on_chunk):
    import soundcard as sc
    import numpy as np

    devices = sc.all_microphones(include_loopback=True)
    device  = None
    for d in devices:
        if "loopback" in d.name.lower():
            device = d
            break
    if device is None and devices:
        device = devices[0]
    if device is None:
        raise RuntimeError("No loopback audio device found")

    logger.info("soundcard loopback: '%s'", device.name)
    with device.recorder(samplerate=SAMPLE_RATE, channels=1) as rec:
        while not stop_event.is_set():
            data    = rec.record(numframes=SAMPLE_RATE)
            samples = data[:, 0] if data.ndim > 1 else data
            on_chunk(samples.astype(np.float32))


class MeetingListener(threading.Thread):
    """
    Records loopback audio and transcribes in real-time every CHUNK_SECONDS.
    on_text(str) is called on the calling thread via the provided callback.
    """

    def __init__(
        self,
        on_text: Optional[Callable[[str], None]] = None,
        language: str = "en-US",
        on_error: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(daemon=True)
        self.language = language
        self.on_text = on_text
        self.on_error = on_error
        self._stop_event = threading.Event()
        self._buffer: list = []          # raw 1-second float32 chunks
        self._lock    = threading.Lock()
        self._transcription_error_reported = False

    def _report_error(self, message: str):
        logger.error("%s", message)
        if self.on_error:
            self.on_error(message)

    def start_listening(self):
        self._stop_event.clear()
        with self._lock:
            self._buffer.clear()
        if not self.is_alive():
            self.start()

    def stop_listening(self):
        self._stop_event.set()

    def _flush_buffer(self):
        """Transcribe whatever is in the buffer and fire the callback."""
        import numpy as np
        with self._lock:
            if not self._buffer:
                return
            samples = np.concatenate(self._buffer)
            self._buffer.clear()

        try:
            text = _transcribe_chunk(samples, self.language)
            self._transcription_error_reported = False
        except Exception as exc:
            if not self._transcription_error_reported:
                message = f"Meeting transcription failed: {exc}"
                if isinstance(exc, ImportError):
                    message += ". Install dependencies from requirements.txt and restart listening."
                self._report_error(message)
                self._transcription_error_reported = True
            self._stop_event.set()
            return

        logger.info("Transcribed: %s", text or "<silent>")
        if text and self.on_text:
            self.on_text(text)

    def run(self):
        seconds_accumulated = 0

        def on_chunk(samples):
            nonlocal seconds_accumulated
            with self._lock:
                self._buffer.append(samples.copy())
            seconds_accumulated += 1
            if seconds_accumulated >= CHUNK_SECONDS:
                seconds_accumulated = 0
                threading.Thread(target=self._flush_buffer, daemon=True).start()

        try:
            _capture_pyaudiowpatch(self._stop_event, on_chunk)
        except ImportError:
            logger.warning("pyaudiowpatch not available, trying soundcard…")
            try:
                _capture_soundcard(self._stop_event, on_chunk)
            except Exception as exc:
                logger.exception("Audio capture failed: %s", exc)
                self._report_error(f"Meeting audio capture failed: {exc}")
        except Exception as exc:
            logger.warning("pyaudiowpatch failed (%s), trying soundcard…", exc)
            try:
                _capture_soundcard(self._stop_event, on_chunk)
            except Exception as exc2:
                logger.exception("Both audio backends failed: %s", exc2)
                self._report_error(f"Meeting audio capture failed: {exc2}")
        # flush any remaining audio when stopped
        self._flush_buffer()
        logger.info("Meeting listener stopped")
