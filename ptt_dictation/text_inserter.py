"""Checks what's currently focused (is it a text box?) and types text into it.

Two ways of typing the text in, tried in order:
1. The clean way: tell the focused field "your selected text is now this,"
   which most native Mac apps treat as replacing the cursor spot with the
   new text, as one single undo step.
2. The fallback: fake actual keystrokes. Needed for apps that don't
   support the clean way properly (some apps built with Electron, like
   Slack). Long text gets typed in small chunks since each fake keystroke
   can only carry so many characters at once.
"""
import time

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    AXUIElementIsAttributeSettable,
)
import Quartz

# Labels that mean "this is a place you can type into." Covers the
# labels some web and Electron apps use for their message/compose boxes too.
TEXT_INPUT_ROLES = {
    "AXTextField",
    "AXTextArea",
    "AXComboBox",
}

# Max characters we can fake-type in one go -- longer text gets split into pieces this size.
_UNICODE_CHUNK_SIZE = 20

# Terminal apps draw their own text instead of using a normal Mac text box,
# so macOS's Accessibility API can't see a focused element in them at all --
# there's nothing to check. Since the whole terminal window is basically
# always "a place you can type," we just trust the app itself instead of
# trying (and failing) to look inside it.
_TERMINAL_BUNDLE_IDS = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "dev.warp.Warp-Stable",
    "co.zeit.hyper",
    "org.alacritty",
    "net.kovidgoyal.kitty",
}

# Rich-text boxes rendered by Chromium's web engine (Jira's comment box,
# Gmail, Notion, VS Code's own webview-based panels, Slack) often claim the
# "clean" text-setting method worked when it actually did nothing -- the
# page's own JavaScript never even saw it happen, so nothing changes on
# screen even though we get a success code back. Fake keystrokes go through
# the same real typing path the page/app listens to, so for anything built
# on Chromium we skip straight to that instead of trusting the "clean" way.
# This covers actual browsers as well as Electron apps (VS Code, Slack),
# since Electron is just Chromium wrapped up as a desktop app.
_BROWSER_BUNDLE_IDS = {
    "com.google.Chrome",
    "com.google.Chrome.beta",
    "com.google.Chrome.canary",
    "com.apple.Safari",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "com.brave.Browser",
    "company.thebrowser.Browser",
    "com.microsoft.VSCode",
    "com.microsoft.VSCodeInsiders",
    "com.vscodium",
    "com.tinyspeck.slackmacgap",
}

_kAXFocusedUIElementAttribute = "AXFocusedUIElement"
_kAXRoleAttribute = "AXRole"
_kAXSelectedTextAttribute = "AXSelectedText"
_kAXErrorSuccess = 0

# Apps built on Electron/Chromium (VS Code, Slack, and VS Code's own
# built-in terminal) don't turn on their full accessibility support by
# default -- normally that only happens when VoiceOver is running. We have
# to explicitly ask the frontmost app to turn it on, once per app, or every
# AX lookup into it comes back empty and we'd wrongly think no text box is
# focused at all.
_enhanced_ui_enabled_pids = set()


def _frontmost_app():
    return NSWorkspace.sharedWorkspace().frontmostApplication()


def frontmost_bundle_id() -> str:
    app = _frontmost_app()
    return app.bundleIdentifier() if app else ""


def frontmost_is_terminal() -> bool:
    return frontmost_bundle_id() in _TERMINAL_BUNDLE_IDS


def frontmost_is_browser() -> bool:
    return frontmost_bundle_id() in _BROWSER_BUNDLE_IDS


# VS Code's own editor and its chat box report a normal focused element
# fine -- but VS Code's built-in terminal panel draws on a canvas just
# like iTerm2 does, so it reports nothing at all, and there's no separate
# app identity to catch it by. So: if VS Code is the frontmost app and we
# get nothing back, we assume that's its terminal panel and treat it the
# same as a real terminal app. (Small tradeoff: this could also fire if
# some other non-text VS Code panel is focused, which is rare and harmless
# since the fallback typing method won't do anything unwanted there.)
_VSCODE_BUNDLE_ID = "com.microsoft.VSCode"


def _should_treat_as_terminal(focused_element_was_empty: bool) -> bool:
    if frontmost_is_terminal():
        return True
    return focused_element_was_empty and frontmost_bundle_id() == _VSCODE_BUNDLE_ID


def _enable_enhanced_accessibility_for_frontmost_app(app_element, pid):
    if pid in _enhanced_ui_enabled_pids:
        return
    _enhanced_ui_enabled_pids.add(pid)
    # Different Chromium-based apps listen for different "turn on
    # accessibility" signals -- Electron apps tend to respond to one,
    # plain Chrome/web content to the other. Setting both is harmless
    # (an app just ignores the one it doesn't use).
    AXUIElementSetAttributeValue(app_element, "AXEnhancedUserInterface", True)
    AXUIElementSetAttributeValue(app_element, "AXManualAccessibility", True)


def get_focused_element():
    """Returns whatever's currently focused, or None if we can't tell
    (Accessibility permission is off, or nothing's focused).

    Asks the frontmost app directly for its focused element, rather than
    going through the shared system-wide lookup -- some apps (Chrome's web
    content, notably) only answer that question correctly when asked this
    way.
    """
    app = _frontmost_app()
    if app is None:
        return None
    pid = app.processIdentifier()
    app_element = AXUIElementCreateApplication(pid)

    err, focused = AXUIElementCopyAttributeValue(
        app_element, _kAXFocusedUIElementAttribute, None
    )
    if err == _kAXErrorSuccess and focused is not None:
        return focused

    # Came back empty -- try switching on full accessibility support for
    # this app (a no-op if it's not Electron/Chromium, or if we've already
    # done it for this app), then give it a moment to build its
    # accessibility tree and look again.
    _enable_enhanced_accessibility_for_frontmost_app(app_element, pid)
    time.sleep(0.15)
    err, focused = AXUIElementCopyAttributeValue(
        app_element, _kAXFocusedUIElementAttribute, None
    )
    if err != _kAXErrorSuccess or focused is None:
        return None
    return focused


def get_role(element) -> str:
    err, role = AXUIElementCopyAttributeValue(element, _kAXRoleAttribute, None)
    return role if err == _kAXErrorSuccess and role else ""


def is_text_input_role(role: str) -> bool:
    return role in TEXT_INPUT_ROLES


def is_value_settable(element) -> bool:
    """Backup check for apps that don't report a normal text-box label
    but still let you set their text value (some web/Electron editors)."""
    err, settable = AXUIElementIsAttributeSettable(element, "AXValue", None)
    return err == _kAXErrorSuccess and bool(settable)


def focused_field_is_text_input() -> tuple:
    """Checks if what's focused right now is a text box, and what its
    label is. Used both when the key is first pressed (to decide whether
    to even start recording) and again right before typing the text in
    (since focus can shift while you were talking)."""
    if frontmost_is_terminal():
        return True, "terminal"

    element = get_focused_element()
    if element is None:
        if _should_treat_as_terminal(focused_element_was_empty=True):
            return True, "vscode terminal (assumed)"
        return False, ""
    role = get_role(element)
    if is_text_input_role(role):
        return True, role
    if is_value_settable(element):
        return True, role or "(settable, non-standard role)"
    return False, role


def _insert_via_ax(text: str) -> bool:
    element = get_focused_element()
    if element is None:
        return False
    err = AXUIElementSetAttributeValue(element, _kAXSelectedTextAttribute, text)
    return err == _kAXErrorSuccess


def _post_unicode_chunk(chunk: str):
    key_down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    key_up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
    Quartz.CGEventKeyboardSetUnicodeString(key_down, len(chunk), chunk)
    Quartz.CGEventKeyboardSetUnicodeString(key_up, len(chunk), chunk)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_up)


def _insert_via_keystrokes(text: str) -> bool:
    try:
        for i in range(0, len(text), _UNICODE_CHUNK_SIZE):
            _post_unicode_chunk(text[i : i + _UNICODE_CHUNK_SIZE])
        return True
    except Exception:
        return False


def insert_text(text: str) -> str:
    """Attempts insertion, returns which method succeeded: 'ax', 'keystroke',
    or 'failed'."""
    if not text:
        return "failed"
    if frontmost_is_browser():
        return "keystroke" if _insert_via_keystrokes(text) else "failed"
    if _should_treat_as_terminal(focused_element_was_empty=get_focused_element() is None):
        return "keystroke" if _insert_via_keystrokes(text) else "failed"
    if _insert_via_ax(text):
        return "ax"
    if _insert_via_keystrokes(text):
        return "keystroke"
    return "failed"
