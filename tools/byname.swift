// Registers a font for this process only, then looks it up by PostScript name and
// shapes 128+256= with it, the way an app like TextEdit finds an installed font.
import CoreText
import Foundation
let url = URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL
var error: Unmanaged<CFError>?
let ok = CTFontManagerRegisterFontsForURL(url, .process, &error)
print("registered:", ok, error.map { String(describing: $0.takeRetainedValue()) } ?? "")
let ps = (CTFontManagerCopyAvailablePostScriptNames() as NSArray).compactMap { $0 as? String }.filter { $0.lowercased().contains("carry") }
print("postscript names:", ps)
let font = CTFontCreateWithName(CommandLine.arguments[2] as CFString, 1000, nil)
print("resolved:", CTFontCopyPostScriptName(font) as String, "| full:", CTFontCopyFullName(font) as String)
let line = CTLineCreateWithAttributedString(NSAttributedString(string: "128+256=", attributes: [kCTFontAttributeName as NSAttributedString.Key: font]))
var names: [String] = []
for run in CTLineGetGlyphRuns(line) as! [CTRun] {
    let n = CTRunGetGlyphCount(run); var g = [CGGlyph](repeating: 0, count: n)
    CTRunGetGlyphs(run, CFRange(location: 0, length: n), &g)
    names += g.map { CTFontCopyNameForGlyph(font, $0) as String? ?? "?" }.filter { $0 != "pad" && $0 != "blank" }
}
print("by-name shaping of 128+256=:", names.joined(separator: " "))
