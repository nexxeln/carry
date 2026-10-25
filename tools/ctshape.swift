// Shapes each line of stdin with CoreText (the engine behind Safari and TextEdit)
// and prints glyph names with advances, in the same format as `hb-shape --no-clusters`.
import CoreText
import Foundation

let args = CommandLine.arguments
guard args.count == 2, let data = FileManager.default.contents(atPath: args[1]) else {
    FileHandle.standardError.write("usage: ctshape font.ttf < lines\n".data(using: .utf8)!)
    exit(2)
}
guard let descriptors = CTFontManagerCreateFontDescriptorsFromData(data as CFData) as? [CTFontDescriptor],
      let descriptor = descriptors.first else {
    FileHandle.standardError.write("could not load font\n".data(using: .utf8)!)
    exit(1)
}
// At a size of 1000 points, advances come back in font units (the font has 1000 units per em).
let font = CTFontCreateWithFontDescriptor(descriptor, 1000, nil)

while let line = readLine(strippingNewline: true) {
    let attributed = NSAttributedString(string: line, attributes: [kCTFontAttributeName as NSAttributedString.Key: font])
    let ctLine = CTLineCreateWithAttributedString(attributed)
    var names: [String] = []
    for run in CTLineGetGlyphRuns(ctLine) as! [CTRun] {
        let count = CTRunGetGlyphCount(run)
        var glyphs = [CGGlyph](repeating: 0, count: count)
        var advances = [CGSize](repeating: .zero, count: count)
        CTRunGetGlyphs(run, CFRange(location: 0, length: count), &glyphs)
        CTRunGetAdvances(run, CFRange(location: 0, length: count), &advances)
        let runFont = (CTRunGetAttributes(run) as NSDictionary)[kCTFontAttributeName] as! CTFont
        for (glyph, advance) in zip(glyphs, advances) {
            let name = CTFontCopyNameForGlyph(runFont, glyph) as String? ?? "gid\(glyph)"
            names.append("\(name)+\(Int(advance.width.rounded()))")
        }
    }
    print("[" + names.joined(separator: "|") + "]")
}
