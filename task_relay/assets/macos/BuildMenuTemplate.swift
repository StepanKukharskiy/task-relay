import AppKit

// Package the monochrome artwork as an alpha-only macOS template. Light
// background pixels are excluded before downsampling to preserve clean edges.
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
let source = NSBitmapImageRep(data: try Data(contentsOf: input))!
let width = source.pixelsWide
let height = source.pixelsHigh
let mask = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                           isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: width * 4, bitsPerPixel: 32)!
let pixels = mask.bitmapData!
for y in 0..<height {
    for x in 0..<width {
        let color = source.colorAt(x: x, y: y)!.usingColorSpace(.deviceRGB)!
        let lightness = max(color.redComponent, color.greenComponent, color.blueComponent)
        let alpha = min(1, max(0, (0.5 - lightness) / 0.3)) * color.alphaComponent
        let offset = y * mask.bytesPerRow + x * 4
        pixels[offset] = 0
        pixels[offset + 1] = 0
        pixels[offset + 2] = 0
        pixels[offset + 3] = UInt8((alpha * 255).rounded())
    }
}
try mask.representation(using: .png, properties: [:])!.write(to: output)
print("Prepared transparent menu-bar template")
