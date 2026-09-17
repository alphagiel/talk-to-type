"""Where the app starts, and where everything gets wired together.

The full loop: check permissions, show the menu bar icon, watch for the
hotkey (only if a text box is focused), record audio, turn it into text,
and type that text into whatever's focused.
"""
import datetime
import threading
import time

import rumps
import sounddevice as sd

from ptt_dictation import config, permissions, text_inserter
from ptt_dictation.audio_recorder import AudioRecorder, rms
from ptt_dictation.hotkey_listener import create_listener
from ptt_dictation.indicator_overlay import IndicatorOverlay
from ptt_dictation.transcriber import Transcriber

FLASH_SECONDS = 1.2
SILENCE_RMS_THRESHOLD = 0.01


def _log(message: str) -> None:
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {message}")


class PTTDictationApp(rumps.App):
    def __init__(self):
        super().__init__("PTT Dictation", title="\U0001F3A4", quit_button=None)
        self.config = config.load_config()
        self.listener = None
        self.recorder = AudioRecorder()
        self.transcriber = Transcriber(model_size=self.config["model_size"])
        self.overlay = IndicatorOverlay()
        self._press_time = None
        self._recording_active = False
        self._busy = False
        self._max_length_timer = None
        # Which app we last successfully typed into -- if you're still in
        # that same app next time, we add a leading space so back-to-back
        # sentences don't run together with no gap between them.
        self._last_insert_bundle_id = None

        self.permissions_item = rumps.MenuItem(
            "Check Permissions", callback=self.check_permissions
        )
        self.hotkey_menu = rumps.MenuItem("Choose Hotkey")
        for key_name, label in config.HOTKEY_LABELS.items():
            item = rumps.MenuItem(
                label, callback=self._make_hotkey_callback(key_name)
            )
            item.state = 1 if self.config["hotkey"] == key_name else 0
            self.hotkey_menu.add(item)

        self.menu = [
            self.permissions_item,
            self.hotkey_menu,
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        self._startup_permission_check()
        self._start_listener()
        self._start_model_loading()

    # -- Transcription model ----------------------------------------------

    def _start_model_loading(self):
        _log(f"Warming up: loading Whisper model '{self.transcriber.model_size}'...")

        def _load():
            self.transcriber.load()
            _log("Model ready.")

        threading.Thread(target=_load, daemon=True).start()

    # -- Permissions -----------------------------------------------------

    def _startup_permission_check(self):
        missing = permissions.missing_permissions()
        if missing:
            _log(permissions.describe_missing(missing))
            rumps.notification(
                "PTT Dictation",
                "Missing permissions",
                permissions.describe_missing(missing),
            )
        else:
            _log("All required permissions granted.")

    def check_permissions(self, _sender):
        missing = permissions.missing_permissions()
        message = permissions.describe_missing(missing)
        _log(message)
        response = rumps.alert(
            title="Permission Status",
            message=message,
            ok="OK",
            cancel="Open Settings" if missing else None,
        )
        # Clicking OK returns 1, clicking "Open Settings" returns 0.
        if missing and response == 0:
            for name in missing:
                permissions.open_settings_pane(name)

    # -- Hotkey selection --------------------------------------------------

    def _make_hotkey_callback(self, key_name):
        def _callback(sender):
            self.config["hotkey"] = key_name
            config.save_config(self.config)
            for item in self.hotkey_menu.values():
                item.state = 1 if item.title == config.HOTKEY_LABELS[key_name] else 0
            _log(f"Hotkey changed to {config.HOTKEY_LABELS[key_name]}")
            self._restart_listener()

        return _callback

    # -- Hotkey listener wiring --------------------------------------------

    def _start_listener(self):
        hotkey_name = self.config["hotkey"]
        _log(f"Starting hotkey listener for: {config.HOTKEY_LABELS.get(hotkey_name, hotkey_name)}")
        self.listener = create_listener(
            hotkey_name, on_down=self._on_hotkey_down, on_up=self._on_hotkey_up
        )
        try:
            self.listener.start()
        except RuntimeError as e:
            _log(f"ERROR: {e}")

    def _restart_listener(self):
        if self.listener:
            self.listener.stop()
        self._start_listener()

    def _flash(self, state: str, seconds: float = FLASH_SECONDS):
        self.overlay.set_state(state)
        threading.Timer(seconds, self.overlay.hide).start()

    def _on_hotkey_down(self):
        if not permissions.check_accessibility():
            _log("ERROR: Accessibility permission not granted, ignoring press.")
            self._flash("error")
            return

        is_valid, role = text_inserter.focused_field_is_text_input()
        if not is_valid:
            # Do nothing at all -- no log, no recording, no indicator.
            # Most of the time this key is pressed with no text box
            # focused (Desktop, Finder, clicking a button), and it should
            # be totally silent.
            return

        _log(f"Hotkey DOWN (focused role: {role!r})")
        if self._busy:
            _log("Still processing the previous recording, ignoring this press.")
            return
        if permissions.microphone_denied():
            _log("ERROR: Microphone permission denied, skipping recording.")
            self._flash("error")
            return
        if not self.transcriber.is_ready:
            _log("Model still warming up, ignoring this press.")
            self._flash("warming_up")
            return
        try:
            self.recorder.start()
        except sd.PortAudioError as e:
            _log(f"ERROR: could not start recording (mic busy?): {e}")
            self._flash("error")
            return
        self._press_time = time.time()
        self._recording_active = True
        self.overlay.set_state("listening")

        # A stuck key (or someone just holding it too long) shouldn't
        # record forever -- auto-stop after the configured max length.
        max_seconds = self.config["max_record_seconds"]
        self._max_length_timer = threading.Timer(max_seconds, self._on_max_length_reached)
        self._max_length_timer.daemon = True
        self._max_length_timer.start()

    def _on_max_length_reached(self):
        _log(f"Max recording length ({self.config['max_record_seconds']}s) reached, auto-stopping.")
        self._on_hotkey_up()

    def _on_hotkey_up(self):
        _log("Hotkey UP")
        if self._max_length_timer:
            self._max_length_timer.cancel()
            self._max_length_timer = None
        if not self._recording_active:
            return
        self._recording_active = False
        self._busy = True
        self.overlay.set_state("transcribing")

        # Stop recording right here since that's quick, but hand off the
        # slow stuff (checking for silence, saving, transcribing) to
        # another thread. This function runs on the same thread that's
        # watching for the hotkey -- if we make it wait too long, Mac
        # will think that key-watching is broken and shut it off.
        buffer, sample_rate = self.recorder.stop()
        held_ms = (time.time() - self._press_time) * 1000 if self._press_time else 0
        threading.Thread(
            target=self._process_recording, args=(buffer, sample_rate, held_ms), daemon=True
        ).start()

    def _process_recording(self, buffer, sample_rate, held_ms):
        try:
            if held_ms < self.config["min_hold_ms"]:
                _log(f"Discarded: held for {held_ms:.0f}ms, below {self.config['min_hold_ms']}ms minimum.")
                self._flash("discarded")
                return

            duration_s = len(buffer) / sample_rate if sample_rate else 0
            amplitude = rms(buffer)
            _log(f"Recorded {duration_s:.2f}s, rms={amplitude:.4f}")

            if amplitude < SILENCE_RMS_THRESHOLD:
                _log("Discarded: audio below silence threshold.")
                self._flash("discarded")
                return

            # Audio never touches disk -- it's transcribed straight from
            # memory and the buffer is dropped right after.
            text = self.transcriber.transcribe(buffer)
            _log(f"TRANSCRIPT: {text!r}")

            if not text:
                _log("Discarded: empty transcript.")
                self._flash("discarded")
                return

            # The focused spot might have changed while you were talking
            # (clicked elsewhere, switched apps, tabbed to a button). Only
            # type the text in if it's still a real text box -- otherwise
            # it'd land in the wrong place, so just drop it instead.
            is_valid, role = text_inserter.focused_field_is_text_input()
            if not is_valid:
                _log(f"Discarded: focus is no longer a text field (role: {role!r}).")
                self._last_insert_bundle_id = None
                self._flash("discarded")
                return

            bundle_id = text_inserter.frontmost_bundle_id()
            if bundle_id and bundle_id == self._last_insert_bundle_id:
                text = " " + text

            method = text_inserter.insert_text(text)
            if method == "failed":
                _log("ERROR: text insertion failed via both AX API and keystroke fallback.")
                self._flash("error")
            else:
                _log(f"Inserted via {method}.")
                self._last_insert_bundle_id = bundle_id
                self.overlay.hide()
        finally:
            self._busy = False

    # -- Lifecycle ---------------------------------------------------------

    def quit_app(self, _sender):
        if self.listener:
            self.listener.stop()
        rumps.quit_application()


def main():
    PTTDictationApp().run()


if __name__ == "__main__":
    main()
