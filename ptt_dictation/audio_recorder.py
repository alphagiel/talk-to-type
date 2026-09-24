"""Records audio while the key is held, keeping it all in memory.

Records at 16kHz mono because that's exactly what Whisper wants — recording
at that rate up front means we never have to convert it later.
"""
import datetime
import threading

import numpy as np
import sounddevice as sd


def _log(message: str) -> None:
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [audio_recorder] {message}")

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
# PortAudio's stop()/close() can hang forever on macOS -- most often when
# the mic list changes mid-recording (a Continuity Camera/iPhone mic
# appearing or disappearing is the usual trigger). If it doesn't respond in
# this long, give up on it rather than freezing the whole app.
STOP_TIMEOUT_SECONDS = 2.0


class AudioRecorder:
    """start() begins recording from the default mic; stop() ends it and
    hands back the recorded audio plus its sample rate.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._stream = None
        self._chunks = []

    def _close_stream_with_timeout(self, stream):
        """Runs stream.stop()/close() on a side thread so a PortAudio hang
        can't freeze the app -- if it doesn't finish in time, we abandon
        that thread (it may leak, but a leaked thread beats a frozen app)
        and move on with whatever audio we already captured.
        """
        done = threading.Event()

        def _teardown():
            _log("calling stream.stop()")
            stream.stop()
            _log("stream.stop() returned, calling stream.close()")
            stream.close()
            _log("stream.close() returned")
            done.set()

        threading.Thread(target=_teardown, daemon=True).start()
        if not done.wait(timeout=STOP_TIMEOUT_SECONDS):
            _log(
                f"stream teardown didn't finish within {STOP_TIMEOUT_SECONDS}s -- "
                "abandoning it and continuing with whatever audio we've got"
            )

    def _callback(self, indata, frames, time_info, status):
        if status:
            # Something glitched (a dropped chunk, etc.) but it's not
            # serious enough to stop recording -- just log it.
            print(f"[audio_recorder] stream status: {status}")
        self._chunks.append(indata.copy())

    def start(self):
        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> tuple:
        _log("stop() called")
        if self._stream is not None:
            self._close_stream_with_timeout(self._stream)
            self._stream = None

        if not self._chunks:
            _log("no chunks recorded, returning empty buffer")
            return np.zeros((0,), dtype=np.float32), self.sample_rate

        _log(f"concatenating {len(self._chunks)} chunks")
        buffer = np.concatenate(self._chunks, axis=0).flatten()
        self._chunks = []
        _log("stop() done")
        return buffer, self.sample_rate


def rms(buffer: np.ndarray) -> float:
    """How loud the audio is on average. Used to spot near-silent recordings."""
    if buffer.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(buffer))))
