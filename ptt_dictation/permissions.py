"""Checks the three Mac permissions this app needs: mic, accessibility, input monitoring.

Each check only returns true if that permission is fully turned on.
Nothing here pops up a permission prompt on its own — except checking
the mic, which triggers Mac's own popup the first time. For the other
two, the user has to flip them on in System Settings, so we send them
straight to the right settings page instead.
"""
import subprocess

from ApplicationServices import AXIsProcessTrusted
from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
from Quartz import CGPreflightListenEventAccess

SETTINGS_URLS = {
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}

# Mic permission status codes.
_AV_DENIED = 2
_AV_AUTHORIZED = 3


def check_microphone() -> bool:
    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    return status == _AV_AUTHORIZED


def microphone_denied() -> bool:
    """True only if the user flat-out said no to mic access.

    Different from "hasn't been asked yet" — in that case we want the
    first real recording attempt to trigger Mac's popup, not skip it quietly.
    """
    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    return status == _AV_DENIED


def check_accessibility() -> bool:
    return bool(AXIsProcessTrusted())


def check_input_monitoring() -> bool:
    return bool(CGPreflightListenEventAccess())


def check_all() -> dict:
    """Returns yes/no for each of the three permissions."""
    return {
        "microphone": check_microphone(),
        "accessibility": check_accessibility(),
        "input_monitoring": check_input_monitoring(),
    }


def missing_permissions() -> list:
    """Returns the names of any permissions that are still off."""
    return [name for name, granted in check_all().items() if not granted]


def open_settings_pane(permission_name: str) -> None:
    """Opens System Settings straight to the page for this permission."""
    url = SETTINGS_URLS.get(permission_name)
    if url:
        subprocess.run(["open", url], check=False)


def describe_missing(missing: list) -> str:
    """Plain message telling the user exactly what to turn on."""
    if not missing:
        return "All required permissions are granted."
    lines = ["Missing permissions:"]
    labels = {
        "microphone": "Microphone (needed to record audio)",
        "accessibility": "Accessibility (needed to insert text into other apps)",
        "input_monitoring": "Input Monitoring (needed to detect the push-to-talk key globally)",
    }
    for name in missing:
        lines.append(f"  - {labels.get(name, name)}")
    lines.append("Open System Settings > Privacy & Security to grant them.")
    return "\n".join(lines)
