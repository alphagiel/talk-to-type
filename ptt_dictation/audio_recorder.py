"""Records audio while the key is held, keeping it all in memory.

Records at 16kHz mono because that's exactly what Whisper wants — recording
at that rate up front means we never have to convert it later.
"""
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"


class AudioRecorder:
    """start() begins recording from the default mic; stop() ends it and
    hands back the recorded audio plus its sample rate.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._stream = None
        self._chunks = []

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
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            return np.zeros((0,), dtype=np.float32), self.sample_rate

        buffer = np.concatenate(self._chunks, axis=0).flatten()
        self._chunks = []
        return buffer, self.sample_rate


def rms(buffer: np.ndarray) -> float:
    """How loud the audio is on average. Used to spot near-silent recordings."""
    if buffer.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(buffer))))
