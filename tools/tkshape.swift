// Lays out each line of stdin with TextKit 1 (NSLayoutManager, the layout engine
// behind TextEdit's text view) and prints glyph names with advances, in the same
// format as `hb-shape --no-clusters`.
import AppKit
import CoreText

let args = CommandLine.arguments
guard args.count == 2, let data = FileManager.default.contents(atPath: args[1]),
      let descriptors = CTFontManagerCreateFontDescriptorsFromData(data as CFData) as? [CTFontDescriptor],
      let descriptor = descriptors.first else {
    FileHandle.standardError.write("usage: tkshape font.ttf < lines\n".data(using: .utf8)!)
    exit(2)
}
let font = CTFontCreateWithFontDescriptor(descriptor, 1000, nil) as NSFont

while let line = readLine(strippingNewline: true) {
    let storage = NSTextStorage(string: line, attributes: [.font: font])
    let layout = NSLayoutManager()
    let container = NSTextContainer(size: NSSize(width: 1e7, height: 1e7))
    container.lineFragmentPadding = 0
    layout.addTextContainer(container)
    storage.addLayoutManager(layout)
    layout.ensureLayout(for: container)
    var names: [String] = []
    for index in 0..<layout.numberOfGlyphs {
        if layout.propertyForGlyph(at: index) == .null { continue }
        let glyph = layout.cgGlyph(at: index)
        let x = layout.location(forGlyphAt: index).x
        let next = index + 1 < layout.numberOfGlyphs ? layout.location(forGlyphAt: index + 1).x : layout.usedRect(for: container).width
        let name = CTFontCopyNameForGlyph(font, glyph) as String? ?? "gid\(glyph)"
        names.append("\(name)+\(Int((next - x).rounded()))")
    }
    print("[" + names.joined(separator: "|") + "]")
}
