// Draws the app icon (1024x1024 PNG) with AppKit -- run by icon/make_icon.sh, which
// turns it into TeetimeMonitor.icns. Kept as a script so the icon is reproducible
// and tweakable without a design tool.
import AppKit

let size: CGFloat = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"

let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8,
    samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
    bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

func color(_ hex: UInt32, _ a: CGFloat = 1) -> NSColor {
    NSColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

// macOS icon grid: the tile is 824pt inside the 1024 canvas, corner radius ~185.
let tile = NSRect(x: 100, y: 100, width: 824, height: 824)
let tilePath = NSBezierPath(roundedRect: tile, xRadius: 185, yRadius: 185)

// Soft drop shadow under the tile.
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 28, color: NSColor.black.withAlphaComponent(0.35).cgColor)
color(0x0F2A38).setFill()
tilePath.fill()
ctx.restoreGState()

// Everything else is clipped to the tile.
ctx.saveGState()
tilePath.addClip()

// Sky: deep teal gradient, matching the app's dark theme.
NSGradient(colors: [color(0x1B4A5E), color(0x0C2230)])!.draw(in: tile, angle: -90)

// A faint sun glow behind the flag.
NSGradient(colors: [color(0xFFD27A, 0.35), color(0xFFD27A, 0)])!
    .draw(fromCenter: NSPoint(x: 600, y: 600), radius: 0, toCenter: NSPoint(x: 600, y: 600), radius: 330, options: [])

// Green: two overlapping rolling hills.
let far = NSBezierPath()
far.move(to: NSPoint(x: 100, y: 100))
far.line(to: NSPoint(x: 100, y: 380))
far.curve(to: NSPoint(x: 924, y: 330), controlPoint1: NSPoint(x: 340, y: 520), controlPoint2: NSPoint(x: 640, y: 250))
far.line(to: NSPoint(x: 924, y: 100))
far.close()
NSGradient(colors: [color(0x2E7D4F), color(0x1E5B3A)])!.draw(in: far, angle: -90)

let near = NSBezierPath()
near.move(to: NSPoint(x: 100, y: 100))
near.line(to: NSPoint(x: 100, y: 270))
near.curve(to: NSPoint(x: 924, y: 300), controlPoint1: NSPoint(x: 380, y: 160), controlPoint2: NSPoint(x: 660, y: 420))
near.line(to: NSPoint(x: 924, y: 100))
near.close()
NSGradient(colors: [color(0x3FA066), color(0x2A7E4C)])!.draw(in: near, angle: -90)

// Flagpole.
let poleX: CGFloat = 560
let poleBottom: CGFloat = 330
let poleTop: CGFloat = 770
color(0xEDEDED).setFill()
NSBezierPath(roundedRect: NSRect(x: poleX - 6, y: poleBottom, width: 12, height: poleTop - poleBottom),
             xRadius: 6, yRadius: 6).fill()

// Flag.
let flag = NSBezierPath()
flag.move(to: NSPoint(x: poleX + 6, y: poleTop))
flag.line(to: NSPoint(x: poleX + 200, y: poleTop - 62))
flag.line(to: NSPoint(x: poleX + 6, y: poleTop - 124))
flag.close()
color(0xF0523D).setFill()
flag.fill()

// Hole shadow + ball resting on the green.
color(0x14452B).setFill()
NSBezierPath(ovalIn: NSRect(x: poleX - 150, y: poleBottom - 50, width: 120, height: 34)).fill()
let ballRect = NSRect(x: 330, y: 318, width: 132, height: 132)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -8), blur: 14, color: NSColor.black.withAlphaComponent(0.35).cgColor)
color(0xFFFFFF).setFill()
NSBezierPath(ovalIn: ballRect).fill()
ctx.restoreGState()
NSGradient(colors: [color(0xFFFFFF), color(0xD9E2E6)])!.draw(in: NSBezierPath(ovalIn: ballRect), angle: -60)
// Dimples.
color(0xB5C2C8).setFill()
for (dx, dy) in [(-30.0, 22.0), (0.0, 38.0), (30.0, 18.0), (-14.0, -6.0), (18.0, -10.0), (-36.0, -28.0), (4.0, -34.0)] {
    NSBezierPath(ovalIn: NSRect(x: ballRect.midX + dx - 8, y: ballRect.midY + dy - 8, width: 16, height: 16)).fill()
}

ctx.restoreGState()
NSGraphicsContext.restoreGraphicsState()

try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
