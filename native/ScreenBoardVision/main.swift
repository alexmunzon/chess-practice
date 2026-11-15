import Foundation

// screen-board-detect IMAGE [IMAGE ...]  -> one JSON object per line.
// Corners are clockwise (y down) starting nearest the image top-left; board orientation
// (which side is white) is not determined, so corners are only defined up to 90-degree rotation.
let args = Array(CommandLine.arguments.dropFirst())
if args.isEmpty || args.contains("--help") {
    FileHandle.standardError.write("usage: screen-board-detect IMAGE [IMAGE ...]\n".data(using: .utf8)!)
    exit(2)
}
let detector = ScreenBoardDetector()
func r3(_ v: Double) -> Double { (v * 1000).rounded() / 1000 }
for path in args {
    var obj: [String: Any] = ["image": path]
    let t0 = Date()
    guard let data = FileManager.default.contents(atPath: path), let image = GrayImage(imageData: data) else {
        obj["found"] = false; obj["reason"] = "unreadable-image"; obj["confidence"] = 0
        print(String(data: try! JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]), encoding: .utf8)!)
        continue
    }
    let t1 = Date()
    let d = detector.detect(image)
    let t2 = Date()
    obj["found"] = d.found
    obj["confidence"] = r3(d.confidence)
    obj["reason"] = d.reason
    if d.found { obj["corners"] = d.corners.map { [r3($0.x), r3($0.y)] } }
    else if !d.corners.isEmpty { obj["rejectedCorners"] = d.corners.map { [r3($0.x), r3($0.y)] } }
    obj["diagnostics"] = ["xCornerCandidates": d.candidates, "latticePoints": d.latticePoints,
                          "span": [d.span.0, d.span.1], "cellAgreement": r3(d.cellAgreement),
                          "ringRatio": r3(d.ringRatio), "placementMargin": r3(d.placementMargin),
                          "fitRmsPx": r3(d.fitRMS)] as [String: Any]
    obj["decodeMs"] = r3(t1.timeIntervalSince(t0) * 1000)
    obj["detectMs"] = r3(t2.timeIntervalSince(t1) * 1000)
    obj["imageSize"] = [image.width, image.height]
    print(String(data: try! JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]), encoding: .utf8)!)
}
