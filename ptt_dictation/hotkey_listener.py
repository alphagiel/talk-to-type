"""Watches for the push-to-talk key being held down or let go, anywhere on the Mac.

Right Option and Right Command are picked up fine by the normal key-tracking
library. Fn doesn't show up reliably that way on Mac, so for Fn we tap
straight into the low-level key event feed instead.

Either way, on_down() fires once when the key goes down, and on_up() fires
once when it comes back up. If the same "down" fires twice in a row (it
shouldn't, but just in case), we ignore the repeat so callers never see
a double press.
"""
import threading

from pynput import keyboard

try:
    import Quartz
except ImportError:  # pragma: no cover - always available on a real Mac
    Quartz = None

# Maps a hotkey name from settings to the actual key it means.
_PYNPUT_KEYS = {
    "right_option": keyboard.Key.alt_r,
    "right_command": keyboard.Key.cmd_r,
}


class HotkeyListener:
    """Common shape every listener follows: start it, stop it, get on_down/on_up calls."""

    def __init__(self, on_down, on_up):
        self.on_down = on_down
        self.on_up = on_up
        self._is_down = False

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def _fire_down(self):
        if not self._is_down:
            self._is_down = True
            self.on_down()

    def _fire_up(self):
        if self._is_down:
            self._is_down = False
            self.on_up()


class PynputHotkeyListener(HotkeyListener):
    """Handles Right Option and Right Command using the normal key-tracking library."""

    def __init__(self, target_key, on_down, on_up):
        super().__init__(on_down, on_up)
        self._target_key = target_key
        self._listener = None

    def _on_press(self, key):
        if key == self._target_key:
            self._fire_down()

    def _on_release(self, key):
        if key == self._target_key:
            self._fire_up()

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None


class FnHotkeyListener(HotkeyListener):
    """Handles the Fn key by tapping straight into the low-level key event feed.

    The normal key-tracking library can't see Fn reliably on Mac — it
    shows up as a modifier-flag change, not a normal key press. So this
    taps into that event feed directly and runs its own listening loop
    on a background thread.
    """

    def __init__(self, on_down, on_up):
        super().__init__(on_down, on_up)
        self._thread = None
        self._run_loop_source = None
        self._tap = None
        self._stop_requested = False

    def _callback(self, proxy, event_type, event, refcon):
        if event_type == Quartz.kCGEventFlagsChanged:
            flags = Quartz.CGEventGetFlags(event)
            fn_down = bool(flags & Quartz.kCGEventFlagMaskSecondaryFn)
            if fn_down:
                self._fire_down()
            else:
                self._fire_up()
        return event

    def _run(self):
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if self._tap is None:
            raise RuntimeError(
                "Couldn't set up Fn key detection -- check Input Monitoring "
                "and Accessibility permissions."
            )
        self._run_loop_source = Quartz.CFMachPortCreateRunLoopSource(
            None, self._tap, 0
        )
        run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(
            run_loop, self._run_loop_source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(self._tap, True)
        while not self._stop_requested:
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.2, False)

    def start(self):
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_requested = True
        if self._tap is not None:
            Quartz.CGEventTapEnable(self._tap, False)


def create_listener(hotkey_name: str, on_down, on_up) -> HotkeyListener:
    """Picks the right listener for whichever key is set in settings."""
    if hotkey_name == "fn":
        return FnHotkeyListener(on_down, on_up)
    if hotkey_name in _PYNPUT_KEYS:
        return PynputHotkeyListener(_PYNPUT_KEYS[hotkey_name], on_down, on_up)
    raise ValueError(f"Unsupported hotkey: {hotkey_name!r}")
