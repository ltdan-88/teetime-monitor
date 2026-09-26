import AppKit
import SwiftUI
@testable import TeetimeMonitorCore

/// Catches exactly the class of bug three direct reports in one day (2026-09-26)
/// turned out to share: a SwiftUI view sized to its own content instead of a fixed
/// column, so something *else* on the same row (a wider weather icon, an extra
/// digit) shifted everything after it sideways relative to the row above or below.
/// `TeetimeMonitorCoreTests`' own assertions never caught any of the three --
/// column position isn't something a value-equality check sees -- and all three
/// were only ever found from a real screenshot. This renders the real views
/// (`DayCardHeader`, `SlotRow` -- the ones the bugs were actually in) off-screen via
/// `ImageRenderer` and diffs the result against a reference PNG committed to this
/// same directory, so a regression fails a build instead of waiting for the next
/// screenshot someone happens to take.
///
/// Two commands:
///
///     swift run VisualRegressionRunner            # compare against References/*.png
///     swift run VisualRegressionRunner --record    # (re)write References/*.png
///
/// A comparison failure writes `<case>.actual.png` and `<case>.diff.png` next to
/// this file's own `Failures/` directory (gitignored) for inspection, and the whole
/// run exits 1 if anything failed or a reference was missing. `--record` always
/// exits 0 -- reviewing the diff before committing a new reference is on the
/// person running it, the same trust `git add` itself already requires.
///
/// **Tolerance, not exact-byte comparison**: font hinting/anti-aliasing can differ
/// in ways too fine to see between macOS versions (this runs on a contributor's own
/// machine and, via `swift-tests`, on GitHub's `macos-latest`, which aren't
/// guaranteed to be the same OS version). A pixel counts as "different" past a
/// per-channel delta of `pixelDeltaThreshold`, and a case only fails once more than
/// `maxDifferentPixelFraction` of the image differs that much -- wide enough to
/// absorb AA noise, narrow enough that a whole icon/column shifting by even a few
/// points still fails.
///
/// **Scope, stated plainly rather than silently assumed**: only pure-SwiftUI views
/// (`Text`/`Image`/`Label`, no AppKit-bridged control) are covered. The Club/Platz
/// row's own course `Picker` (an `NSPopUpButton` under the hood) is a real
/// candidate for the same alignment-bug class, but `NSViewRepresentable` content
/// reliably drawing outside a real, on-screen `NSWindow` isn't confirmed -- adding
/// it means confirming that first, not assuming `ImageRenderer` treats it the same
/// as native SwiftUI content.
enum VisualRegression {
    static let pixelDeltaThreshold: UInt8 = 30
    static let maxDifferentPixelFraction: Double = 0.005

    private static let sourceDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    private static let referencesDirectory = sourceDirectory.appendingPathComponent("References")
    private static let failuresDirectory = sourceDirectory.appendingPathComponent("Failures")

    @MainActor
    static func run(record: Bool) -> Bool {
        prepareDeterministicEnvironment()
        var allPassed = true
        for testCase in allCases {
            guard let pngData = renderPNG(testCase.view(), size: testCase.size) else {
                print("✗ \(testCase.name): ImageRenderer produced no image")
                allPassed = false
                continue
            }
            let referencePath = referencesDirectory.appendingPathComponent("\(testCase.name).png")
            if record {
                try? FileManager.default.createDirectory(at: referencesDirectory, withIntermediateDirectories: true)
                try? pngData.write(to: referencePath)
                print("recorded \(testCase.name).png (\(pngData.count) bytes)")
                continue
            }
            guard let referenceData = try? Data(contentsOf: referencePath) else {
                print("✗ \(testCase.name): no reference at \(referencePath.path) -- run with --record first")
                allPassed = false
                continue
            }
            switch compare(actual: pngData, reference: referenceData) {
            case .match:
                print("✓ \(testCase.name)")
            case .sizeMismatch(let actualSize, let referenceSize):
                print("✗ \(testCase.name): size changed (reference \(referenceSize) -> actual \(actualSize))")
                writeFailureArtifacts(name: testCase.name, actual: pngData)
                allPassed = false
            case .pixelsDiffer(let fraction, let diffImage):
                print("✗ \(testCase.name): \(String(format: "%.3f", fraction * 100))% of pixels differ "
                      + "(allowed \(String(format: "%.3f", maxDifferentPixelFraction * 100))%)")
                writeFailureArtifacts(name: testCase.name, actual: pngData, diff: diffImage)
                allPassed = false
            }
        }
        return allPassed
    }

    /// Every singleton view state in these fixtures reads from -- `AppTheme`/
    /// `AppScale`/`AppUnits`/`AppLanguage`'s own `.shared` first-access already
    /// reads real (or default, if absent) values off this machine's own
    /// `~/.config/teetime-monitor/config`/`preferences.yaml` -- overridden here so
    /// a reference recorded on one machine still matches a comparison run on
    /// another with different saved settings.
    @MainActor
    private static func prepareDeterministicEnvironment() {
        AppTheme.shared.name = "catppuccin"
        AppScale.shared.option = .small
        AppUnits.shared.value = "metric"
        AppLanguage.shared.code = "en"
    }

    @MainActor
    private static func renderPNG<V: View>(_ view: V, size: CGSize) -> Data? {
        let hosted = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(AppTheme.shared.colors.background)
            .environment(\.colorScheme, AppTheme.shared.colors.isDark ? .dark : .light)
        let renderer = ImageRenderer(content: hosted)
        renderer.proposedSize = ProposedViewSize(width: size.width, height: size.height)
        renderer.isOpaque = true
        guard let cgImage = renderer.cgImage else { return nil }
        guard let rep = NSBitmapImageRep(cgImage: cgImage).representation(using: .png, properties: [:]) else {
            return nil
        }
        return rep
    }

    private enum ComparisonResult {
        case match
        case sizeMismatch(actual: CGSize, reference: CGSize)
        case pixelsDiffer(fraction: Double, diffImage: Data?)
    }

    /// Both PNGs are decoded into the *same* fixed pixel format (8bpc RGBA,
    /// premultiplied, no color management) before comparing raw bytes -- so a
    /// format difference between however `ImageRenderer` happened to encode this
    /// run's PNG and whatever encoded the stored reference can't itself register
    /// as a pixel difference.
    private static func compare(actual actualData: Data, reference referenceData: Data) -> ComparisonResult {
        guard let actual = pixelBuffer(from: actualData), let reference = pixelBuffer(from: referenceData) else {
            return .pixelsDiffer(fraction: 1, diffImage: nil)
        }
        guard actual.width == reference.width, actual.height == reference.height else {
            return .sizeMismatch(
                actual: CGSize(width: actual.width, height: actual.height),
                reference: CGSize(width: reference.width, height: reference.height))
        }
        var differentPixels = 0
        var diffPixels = [UInt8](repeating: 0, count: actual.bytes.count)
        let pixelCount = actual.width * actual.height
        for i in 0..<pixelCount {
            let base = i * 4
            var pixelDiffers = false
            for channel in 0..<3 {  // RGB only -- alpha is always 255 (isOpaque render)
                let delta = abs(Int(actual.bytes[base + channel]) - Int(reference.bytes[base + channel]))
                if delta > Int(pixelDeltaThreshold) { pixelDiffers = true }
            }
            if pixelDiffers {
                differentPixels += 1
                // Diff image: red where different, a dim copy of the actual render
                // elsewhere -- enough to spot *which* column moved at a glance.
                diffPixels[base] = 255
                diffPixels[base + 1] = 0
                diffPixels[base + 2] = 0
                diffPixels[base + 3] = 255
            } else {
                diffPixels[base] = actual.bytes[base] / 3
                diffPixels[base + 1] = actual.bytes[base + 1] / 3
                diffPixels[base + 2] = actual.bytes[base + 2] / 3
                diffPixels[base + 3] = 255
            }
        }
        let fraction = Double(differentPixels) / Double(max(pixelCount, 1))
        if fraction <= maxDifferentPixelFraction { return .match }
        let diffImage = pngData(fromRGBA: diffPixels, width: actual.width, height: actual.height)
        return .pixelsDiffer(fraction: fraction, diffImage: diffImage)
    }

    private static func writeFailureArtifacts(name: String, actual: Data, diff: Data? = nil) {
        try? FileManager.default.createDirectory(at: failuresDirectory, withIntermediateDirectories: true)
        try? actual.write(to: failuresDirectory.appendingPathComponent("\(name).actual.png"))
        if let diff {
            try? diff.write(to: failuresDirectory.appendingPathComponent("\(name).diff.png"))
        }
        print("  -> wrote \(failuresDirectory.appendingPathComponent(name).path).{actual,diff}.png")
    }

    private static func pixelBuffer(from pngData: Data) -> (width: Int, height: Int, bytes: [UInt8])? {
        guard let source = CGImageSourceCreateWithData(pngData as CFData, nil),
              let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return nil }
        let width = cgImage.width, height = cgImage.height
        var bytes = [UInt8](repeating: 0, count: width * height * 4)
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: &bytes, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
            space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
        return (width, height, bytes)
    }

    private static func pngData(fromRGBA bytes: [UInt8], width: Int, height: Int) -> Data? {
        var mutableBytes = bytes
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: &mutableBytes, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
            space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ), let cgImage = context.makeImage() else { return nil }
        return NSBitmapImageRep(cgImage: cgImage).representation(using: .png, properties: [:])
    }
}

let arguments = CommandLine.arguments
let recordMode = arguments.contains("--record")
let passed = MainActor.assumeIsolated { VisualRegression.run(record: recordMode) }
if !recordMode {
    print(passed ? "\nAll visual regression checks passed." : "\nVisual regression check(s) failed.")
}
exit(passed ? 0 : 1)
