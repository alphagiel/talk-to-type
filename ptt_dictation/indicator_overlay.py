"""A small floating pill that shows what the app is doing right now.

It sits near the bottom of the screen, stays on top of everything, and
never steals focus away from whatever text field you're actually typing
into.

You can call its methods from any thread -- it takes care of sending the
actual screen update to the main thread itself.
"""
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSImage,
    NSImageView,
    NSLayoutAttributeCenterY,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStackView,
    NSTextAlignmentCenter,
    NSTextField,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSWindowStyleMaskNonactivatingPanel,
)
from Quartz import CABasicAnimation
from PyObjCTools import AppHelper

_WIDTH = 180
_HEIGHT = 44
_BOTTOM_MARGIN = 80
_ICON_SIZE = 15
_STACK_SPACING = 6
_PULSE_ANIMATION_KEY = "pulse"
_BORDER_WIDTH = 3.0
_GOLD = (1.0, 0.84, 0.0)

# state -> (label text, background color as (r, g, b, a), SF Symbol name)
_STATES = {
    "idle": (None, None, None),
    "warming_up": ("Warming up...", (0.55, 0.55, 0.55, 0.92), "hourglass"),
    "listening": ("Listening...", (0.20, 0.55, 0.95, 0.92), "mic.fill"),
    "transcribing": ("Transcribing...", (0.55, 0.35, 0.85, 0.92), "waveform"),
    "discarded": ("Discarded", (0.65, 0.55, 0.10, 0.92), "trash"),
    "error": ("Error", (0.85, 0.20, 0.20, 0.92), "exclamationmark.triangle.fill"),
}


class IndicatorOverlay:
    def __init__(self):
        self._panel = None
        self._label = None
        self._icon = None
        self._build()

    def _build(self):
        screen_frame = NSScreen.mainScreen().frame()
        x = screen_frame.origin.x + (screen_frame.size.width - _WIDTH) / 2
        y = screen_frame.origin.y + _BOTTOM_MARGIN
        rect = NSMakeRect(x, y, _WIDTH, _HEIGHT)

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setCanHide_(False)

        content_view = panel.contentView()
        content_view.setWantsLayer_(True)
        content_view.layer().setCornerRadius_(12.0)

        icon = NSImageView.alloc().init()
        icon.setContentTintColor_(NSColor.whiteColor())
        icon.setTranslatesAutoresizingMaskIntoConstraints_(False)
        icon.widthAnchor().constraintEqualToConstant_(_ICON_SIZE).setActive_(True)
        icon.heightAnchor().constraintEqualToConstant_(_ICON_SIZE).setActive_(True)

        label = NSTextField.alloc().init()
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setAlignment_(NSTextAlignmentCenter)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.boldSystemFontOfSize_(13))
        label.cell().setUsesSingleLineMode_(True)
        label.setTranslatesAutoresizingMaskIntoConstraints_(False)

        # Icon + text as one horizontally-centered group, so the pair
        # stays centered together no matter which state's text is showing.
        stack = NSStackView.alloc().init()
        stack.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        stack.setAlignment_(NSLayoutAttributeCenterY)
        stack.setSpacing_(_STACK_SPACING)
        stack.addArrangedSubview_(icon)
        stack.addArrangedSubview_(label)
        stack.setTranslatesAutoresizingMaskIntoConstraints_(False)
        content_view.addSubview_(stack)

        stack.centerXAnchor().constraintEqualToAnchor_(content_view.centerXAnchor()).setActive_(True)
        stack.centerYAnchor().constraintEqualToAnchor_(content_view.centerYAnchor()).setActive_(True)

        self._panel = panel
        self._label = label
        self._icon = icon

    def _start_pulse(self):
        layer = self._panel.contentView().layer()
        gold_r, gold_g, gold_b = _GOLD
        dim_color = NSColor.colorWithRed_green_blue_alpha_(gold_r, gold_g, gold_b, 0.25).CGColor()
        bright_color = NSColor.colorWithRed_green_blue_alpha_(gold_r, gold_g, gold_b, 1.0).CGColor()

        layer.setBorderWidth_(_BORDER_WIDTH)
        layer.setBorderColor_(bright_color)

        # Pulse the border's color between dim and bright instead of
        # fading the whole pill -- the background stays fully solid.
        animation = CABasicAnimation.animationWithKeyPath_("borderColor")
        animation.setFromValue_(dim_color)
        animation.setToValue_(bright_color)
        animation.setDuration_(0.7)
        animation.setAutoreverses_(True)
        animation.setRepeatCount_(float("inf"))
        layer.addAnimation_forKey_(animation, _PULSE_ANIMATION_KEY)

    def _stop_pulse(self):
        layer = self._panel.contentView().layer()
        layer.removeAnimationForKey_(_PULSE_ANIMATION_KEY)
        layer.setBorderWidth_(0.0)

    def _apply_state(self, state: str):
        text, color, symbol_name = _STATES.get(state, (None, None, None))
        if text is None:
            self._stop_pulse()
            self._panel.orderOut_(None)
            return

        r, g, b, a = color
        self._panel.contentView().layer().setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).CGColor()
        )
        self._label.setStringValue_(text)
        self._icon.setImage_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
        )
        self._panel.orderFrontRegardless()

        if state == "listening":
            self._start_pulse()
        else:
            self._stop_pulse()

    def set_state(self, state: str):
        """Safe to call from any thread -- queues the actual screen update for the main thread."""
        AppHelper.callAfter(self._apply_state, state)

    def hide(self):
        self.set_state("idle")
