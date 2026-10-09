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
# Same story for opening/starting the stream.
START_TIMEOUT_SECONDS = 2.0


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
            stream.stop()
            stream.close()
            done.set()

        threading.Thread(target=_teardown, daemon=True).start()
        if not done.wait(timeout=STOP_TIMEOUT_SECONDS):
            _log(
                f"stream teardown didn't finish within {STOP_TIMEOUT_SECONDS}s -- "
                "abandoning it and continuing with whatever audio we've got"
            )

    def start(self):
        # Each recording gets its own chunk list, bound into its own
        # callback -- so a stale stream still being torn down on another
        # thread can never append into (or wipe) a newer recording's audio.
        chunks = []

        def _callback(indata, frames, time_info, status):
            if status:
                # Something glitched (a dropped chunk, etc.) but it's not
                # serious enough to stop recording -- just log it.
                print(f"[audio_recorder] stream status: {status}")
            chunks.append(indata.copy())

        self._chunks = chunks
        self._stream = self._open_stream_with_timeout(_callback)

    def _open_stream_with_timeout(self, callback):
        """Opens and starts the mic stream on a side thread -- PortAudio can
        hang on start just like on stop. If it doesn't come up in time, raise
        PortAudioError like any other mic failure; if it does come up late,
        the side thread shuts it straight back down so no orphaned stream is
        left holding the mic.
        """
        done = threading.Event()
        result = {}
        lock = threading.Lock()

        def _open():
            try:
                stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    callback=callback,
                )
                stream.start()
            except Exception as e:
                result["error"] = e
                done.set()
                return
            with lock:
                if result.get("abandoned"):
                    stream.stop()
                    stream.close()
                    return
                result["stream"] = stream
                done.set()

        threading.Thread(target=_open, daemon=True).start()
        if not done.wait(timeout=START_TIMEOUT_SECONDS):
            with lock:
                if "stream" not in result and "error" not in result:
                    result["abandoned"] = True
            if result.get("abandoned"):
                _log(f"stream start didn't finish within {START_TIMEOUT_SECONDS}s -- giving up on it")
                raise sd.PortAudioError("timed out starting the mic stream")
        if "error" in result:
            raise result["error"]
        return result["stream"]

    def detach(self) -> tuple:
        """Instantly hands off the live recording as (stream, chunks) and
        resets the recorder so start() can be called again. Never blocks --
        pass the result to finish() on a background thread.
        """
        stream, chunks = self._stream, self._chunks
        self._stream, self._chunks = None, []
        return stream, chunks

    def finish(self, stream, chunks) -> tuple:
        """Tears down a detached stream (slow, can hang) and returns the audio."""
        if stream is not None:
            self._close_stream_with_timeout(stream)

        if not chunks:
            return np.zeros((0,), dtype=np.float32), self.sample_rate

        buffer = np.concatenate(chunks, axis=0).flatten()
        return buffer, self.sample_rate

    def stop(self) -> tuple:
        return self.finish(*self.detach())


def rms(buffer: np.ndarray) -> float:
    """How loud the audio is on average. Used to spot near-silent recordings."""
    if buffer.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(buffer))))
