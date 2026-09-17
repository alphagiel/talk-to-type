"""Loads the speech-to-text model once, then turns recorded audio into text.

Loading the model takes a few seconds, so load it on a background thread
at startup and check is_ready before trying to transcribe anything --
see the "warming up" handling in main.py.
"""
import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    def __init__(self, model_size: str = "small.en", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Loads the model. This takes a few seconds, so run it on a background thread."""
        self._model = WhisperModel(
            self.model_size, device=self.device, compute_type=self.compute_type
        )

    def transcribe(self, buffer: np.ndarray) -> str:
        """The audio you pass in must be recorded at 16kHz -- that's the rate
        the model expects."""
        if self._model is None:
            raise RuntimeError("Model is not loaded yet.")

        language = "en" if self.model_size.endswith(".en") else None
        segments, _info = self._model.transcribe(buffer, language=language)
        return "".join(segment.text for segment in segments).strip()
