"""Vlastní floating overlay pro proaktivní upozornění — nahrazuje macOS
notifikaci (ta je vždy vpravo nahoře, mimo pole pozornosti při hovoru).

Spouští se jako samostatný proces (vlastní NSApplication run loop), zobrazí
poloprůhledné okénko uprostřed hlavní obrazovky, po N sekundách se samo
zavře. Nekrade focus (accessory activation policy, ignoruje myš).

Použití: python overlay_notify.py "text" [duration_seconds] [play_sound: 0/1]
"""
import sys

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
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


def main():
    if len(sys.argv) < 2:
        return
    text = sys.argv[1]
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    play_sound = len(sys.argv) > 3 and sys.argv[3] == "1"

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

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
    # Vyloučit ze screen capture — nezobrazí se ve sdílení obrazovky (Meet/
    # Zoom), nahrávání ani screenshotech. Okno je vidět jen na tvém displeji.
    window.setSharingType_(NSWindowSharingNone)

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

    if play_sound:
        sound = NSSound.soundNamed_("Glass")
        if sound:
            sound.play()

    def _quit(timer):
        app.terminate_(None)

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(duration, False, _quit)
    app.run()


if __name__ == "__main__":
    main()
