"""Vygeneruje PNG ikonu Menthol (🌿 na zeleném squircle) do /tmp/menthol_icon.png.
Spouští se v build venv (pyobjc). Následně install.sh udělá .icns přes iconutil.
"""
import AppKit
import Foundation

SIZE = 1024
OUT = "/tmp/menthol_icon.png"


def main():
    img = AppKit.NSImage.alloc().initWithSize_((SIZE, SIZE))
    img.lockFocus()

    rect = Foundation.NSMakeRect(0, 0, SIZE, SIZE)
    radius = SIZE * 0.22
    path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        rect, radius, radius
    )
    # tmavě zelené pozadí
    AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
        0.05, 0.20, 0.15, 1.0
    ).set()
    path.fill()

    # 🌿 uprostřed
    emoji = Foundation.NSString.stringWithString_("🌿")
    font = AppKit.NSFont.systemFontOfSize_(620)
    attrs = {AppKit.NSFontAttributeName: font}
    sz = emoji.sizeWithAttributes_(attrs)
    pt = ((SIZE - sz.width) / 2.0, (SIZE - sz.height) / 2.0)
    emoji.drawAtPoint_withAttributes_(pt, attrs)

    img.unlockFocus()

    tiff = img.TIFFRepresentation()
    rep = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
    png = rep.representationUsingType_properties_(
        AppKit.NSBitmapImageFileTypePNG, {}
    )
    png.writeToFile_atomically_(OUT, True)
    print("OK", OUT)


if __name__ == "__main__":
    main()
