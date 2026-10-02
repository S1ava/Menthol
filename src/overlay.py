"""In-process floating overlay uprostřed obrazovky (pro menubar app).

Používá sdílený NSApplication, který drží rumps. Volat lze z libovolného
vlákna přes show() — marshaluje se na hlavní vlákno přes AppHelper.callAfter.
Okno se samo zavře po `duration` s, nekrade focus a je vyloučené ze sdílení
obrazovky (NSWindowSharingNone), takže ho protistrana v Meetu nevidí.

Nahrazuje spouštění overlay_notify.py jako subprocesu, které v py2app bundlu
nefunguje (sys.executable je sama appka).
"""
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSSound,
    NSTextAlignmentCenter,
    NSTextField,
    NSScreen,
    NSWindow,
    NSWindowSharingNone,
    NSWindowStyleMaskBorderless,
)
from Quartz import CGSizeMake
from Foundation import NSTimer
from PyObjCTools import AppHelper

# Drž reference na živá okna, ať je GC nesebere dřív, než se zavřou.
_windows = []


def _make_window(text, duration, play_sound):
    screen_frame = NSScreen.mainScreen().frame()
    width, height = 520, 130
    x = screen_frame.size.width / 2 - width / 2
    y = screen_frame.size.height / 2 - height / 2

    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, width, height),
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    window.setLevel_(NSFloatingWindowLevel)
    window.setOpaque_(False)
    window.setBackgroundColor_(
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.04, 0.16, 0.12, 0.55)
    )
    window.setHasShadow_(True)
    window.setIgnoresMouseEvents_(True)
    window.setSharingType_(NSWindowSharingNone)  # neviditelné ve sdílení obrazovky

    content = window.contentView()
    content.setWantsLayer_(True)
    content.layer().setCornerRadius_(16.0)
    content.layer().setMasksToBounds_(True)

    label = NSTextField.alloc().initWithFrame_(
        NSMakeRect(20, 20, width - 40, height - 40)
    )
    label.setStringValue_(f"🌿 {text}")
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(NSTextAlignmentCenter)
    label.setTextColor_(NSColor.whiteColor())
    label.setFont_(NSFont.boldSystemFontOfSize_(19))
    label.cell().setWraps_(True)
    label.setUsesSingleLineMode_(False)
    label.setWantsLayer_(True)
    label.layer().setShadowColor_(NSColor.blackColor().CGColor())
    label.layer().setShadowOpacity_(0.8)
    label.layer().setShadowRadius_(4.0)
    label.layer().setShadowOffset_(CGSizeMake(0, -1))
    content.addSubview_(label)

    window.orderFrontRegardless()
    _windows.append(window)

    if play_sound:
        snd = NSSound.soundNamed_("Glass")
        if snd:
            snd.play()

    def _close(timer):
        try:
            window.orderOut_(None)
        except Exception:
            pass
        try:
            _windows.remove(window)
        except ValueError:
            pass

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(float(duration), False, _close)


def show(text, duration=6.0, play_sound=False):
    """Zobrazí overlay. Bezpečné z libovolného vlákna — vykreslení proběhne
    na hlavním vlákně přes AppHelper.callAfter."""
    text = (text or "").strip()
    if not text:
        return
    AppHelper.callAfter(_make_window, text, float(duration), bool(play_sound))
