import CoreGraphics
import Foundation
import ImageIO

// screen-occupancy: Swift port of rectification + square reader v3. See README.md for the conventions.
//   screen-occupancy calibrate --image START.png --corners x,y,x,y,x,y,x,y --rotation R|auto
//                              (--occupancy 64xe/w/b | --fen FEN) --out cal.json [--panel-out p.png]
//   screen-occupancy classify  --image FRAME.png --corners ... --rotation R --calibration cal.json [--panel-out p.png]
//   screen-occupancy batch     --jobs jobs.jsonl|-        (one JSON job per line, one JSON result per line)
//   screen-occupancy policy | --self-test
// --panel P.png may replace --image/--corners (an already rectified 640x640 panel; rectify time 0).

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ a: UInt64, _ b: UInt64) -> Double { OccupancyV3.round(Double(b - a) / 1e6, 3) }
/// CPU time of this thread (the machine is shared, so wall time alone overstates the work).
func cpuNow() -> UInt64 { clock_gettime_nsec_np(CLOCK_THREAD_CPUTIME_ID) }
var cpuAfterDecode: UInt64 = 0

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(2)
}

func parseCorners(_ any: Any?) -> [Point2]? {
    var nums: [Double] = []
    if let s = any as? String {
        nums = s.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        if nums.count != s.split(separator: ",").count { return nil }
    } else if let a = any as? [Any] {
        for x in a {
            if let p = x as? [Any] { nums += p.compactMap { ($0 as? NSNumber)?.doubleValue } }
            else if let n = x as? NSNumber { nums.append(n.doubleValue) }
        }
    }
    guard nums.count == 8, nums.allSatisfy({ $0.isFinite }) else { return nil }
    return (0..<4).map { Point2(x: nums[2 * $0], y: nums[2 * $0 + 1]) }
}

func occupancyFromFEN(_ fen: String) -> [String]? {
    var out: [String] = []
    for ch in fen.split(separator: " ").first ?? "" where ch != "/" {
        if let d = ch.wholeNumberValue { out += Array(repeating: "empty", count: d) }
        else { out.append(ch.isUppercase ? "white" : "black") }
    }
    return out.count == 64 ? out : nil
}

func occupancyFromChars(_ s: String) -> [String]? {
    let map: [Character: String] = ["e": "empty", ".": "empty", "w": "white", "b": "black"]
    let out = s.compactMap { map[$0] }
    return out.count == 64 && s.count == 64 ? out : nil
}

let short: [String: String] = ["empty": ".", "white": "w", "black": "b", "unknown": "?"]

func writePNG(_ img: OccupancyRGBImage, _ path: String) -> Bool {
    var rgba = [UInt8](repeating: 255, count: img.width * img.height * 4)
    for p in 0..<(img.width * img.height) { for c in 0..<3 { rgba[p * 4 + c] = img.pixels[p * 3 + c] } }
    guard let provider = CGDataProvider(data: Data(rgba) as CFData),
          let cg = CGImage(width: img.width, height: img.height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: img.width * 4,
                           space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                           provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent),
          let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, "public.png" as CFString, 1, nil)
    else { return false }
    CGImageDestinationAddImage(dest, cg, nil)
    return CGImageDestinationFinalize(dest)
}

/// Loads the job's picture and returns the prepared screen-upright panel plus timings.
func preparePanel(_ job: [String: Any], _ timings: inout [(String, Any)]) throws -> OccupancyV3.Prepared {
    let t0 = now()
    let panel: OccupancyRGBImage
    if let p = job["panel"] as? String {
        guard let data = FileManager.default.contents(atPath: p) else { throw OccupancyImageError.unreadable }
        panel = try OccupancyImageDecoder.decode(data)
        guard panel.width == 640, panel.height == 640 else { throw OccupancyImageError.unsupported }
        let t1 = now()
        cpuAfterDecode = cpuNow()
        timings += [("decode", ms(t0, t1)), ("rectify", 0.0)]
    } else {
        guard let p = job["image"] as? String, let data = FileManager.default.contents(atPath: p) else {
            throw OccupancyImageError.unreadable
        }
        let image = try OccupancyImageDecoder.decode(data)
        let t1 = now()
        cpuAfterDecode = cpuNow()
        guard let corners = parseCorners(job["corners"]) else { throw JobError("bad-corners") }
        guard let rect = PanelRectifier.rectify(image, corners: corners) else { throw JobError("rectify-failed") }
        panel = rect
        timings += [("decode", ms(t0, t1)), ("rectify", ms(t1, now()))]
    }
    if let out = job["panelOut"] as? String, !writePNG(panel, out) { throw JobError("panel-write-failed") }
    let t2 = now()
    let prepared = OccupancyV3.prepare(panel)
    timings.append(("blur", ms(t2, now())))
    return prepared
}

struct JobError: Error, CustomStringConvertible { let description: String; init(_ s: String) { description = s } }

func rotationOf(_ any: Any?) -> Int?? {  // nil = invalid, .some(nil) = auto
    if any == nil { return .some(nil) }
    if let s = any as? String { if s == "auto" { return .some(nil) }; if let r = Int(s), (0..<4).contains(r) { return r }; return nil }
    if let n = any as? NSNumber, (0..<4).contains(n.intValue) { return n.intValue }
    return nil
}

var calibrations: [String: (OccupancyV3.Calibration, Int)] = [:]

func runCalibrate(_ job: [String: Any]) -> [(String, Any)] {
    var res: [(String, Any)] = [("op", "calibrate"), ("id", job["id"] ?? NSNull()), ("image", job["image"] ?? job["panel"] ?? NSNull())]
    var timings: [(String, Any)] = []
    let occ: [String]?
    if let s = job["occupancy"] as? String { occ = occupancyFromChars(s) } else if let f = job["fen"] as? String { occ = occupancyFromFEN(f) } else { occ = nil }
    guard let occA8 = occ else { return res + [("ok", false), ("error", "bad-occupancy")] }
    guard let rot = rotationOf(job["rotation"]) else { return res + [("ok", false), ("error", "bad-rotation")] }
    do {
        let prepared = try preparePanel(job, &timings)
        let t = now()
        var ok: [(Int, OccupancyV3.Calibration)] = []
        var tried: [Any] = []
        for r in rot.map({ [$0] }) ?? [0, 1, 2, 3] {
            do {
                let cal = try OccupancyV3.calibrate(prepared, occupancy: OccupancyV3.screenFromA8(occA8, r))
                ok.append((r, cal)); tried.append([("rotation", r), ("calibrated", true)] as [(String, Any)])
            } catch let e as OccupancyV3.CalibrationError {
                tried.append([("rotation", r), ("calibrated", false), ("error", e.message),
                              ("problems", e.problems.map { [$0.0, $0.1] })] as [(String, Any)])
            }
        }
        timings.append(("calibrate", ms(t, now())))
        res.append(("rotationsTried", tried))
        if ok.count == 1 {
            let (r, cal) = ok[0]
            let doc = OccupancyJSON.calibrationJSON(cal, extra: [("rotation", r), ("implementation", "swift")])
            if let out = job["out"] as? String {
                try (OccupancyJSON.encode(doc) + "\n").write(toFile: out, atomically: true, encoding: .utf8)
            }
            if let id = job["id"] as? String { calibrations[id] = (cal, r) }
            res += [("ok", true), ("rotation", r), ("calibration", doc)]
        } else {
            res += [("ok", false), ("rotation", NSNull()), ("error", "\(ok.count)-rotations-calibrated")]
        }
    } catch {
        res += [("ok", false), ("error", "\(error)")]
    }
    return res + [("timingsMs", timings)]
}

func runClassify(_ job: [String: Any]) -> [(String, Any)] {
    var res: [(String, Any)] = [("op", "classify"), ("id", job["id"] ?? NSNull()), ("image", job["image"] ?? job["panel"] ?? NSNull())]
    var timings: [(String, Any)] = []
    var cal: OccupancyV3.Calibration?
    var rot = rotationOf(job["rotation"]) ?? nil
    if let ref = job["calibrationRef"] as? String, let c = calibrations[ref] { cal = c.0; if rot == nil { rot = c.1 } }
    else if let path = job["calibration"] as? String, let data = FileManager.default.contents(atPath: path),
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
        cal = OccupancyJSON.calibration(from: obj)
        if rot == nil, let r = obj["rotation"] as? NSNumber { rot = r.intValue }
    }
    guard let calibration = cal else { return res + [("ok", false), ("error", "no-calibration")] }
    guard let r = rot else { return res + [("ok", false), ("error", "bad-rotation")] }
    do {
        let prepared = try preparePanel(job, &timings)
        let t = now()
        let cells = OccupancyV3.classify(prepared, calibration: calibration)
        let t2 = now()
        timings.append(("classify", ms(t, t2)))
        timings.append(("cpuRectifyPlusClassify", ms(cpuAfterDecode, cpuNow())))
        let screen = cells.map { $0.label }
        let board = OccupancyV3.a8FromScreen(screen, r)
        var cellJSON: [Any] = []
        for (i, c) in cells.enumerated() {
            var o: [(String, Any)] = [("square", OccupancyV3.squares[i]), ("label", c.label), ("confidence", c.confidence),
                                      ("reasons", c.reasons)]
            if let raw = c.rawLabel { o.append(("rawLabel", raw)) }
            cellJSON.append(o + c.detail)
        }
        res += [("ok", true), ("rotation", r), ("labels", board.map { short[$0]! }.joined()),
                ("screenLabels", screen.map { short[$0]! }.joined()), ("cells", cellJSON)]
    } catch {
        res += [("ok", false), ("error", "\(error)")]
    }
    let total = timings.compactMap { (["rectify", "blur", "classify"].contains($0.0) ? $0.1 as? Double : nil) }.reduce(0, +)
    return res + [("timingsMs", timings + [("rectifyPlusClassify", OccupancyV3.round(total, 3))])]
}

func flags(_ args: [String]) -> [String: String] {
    var d: [String: String] = [:]
    var i = 0
    while i < args.count {
        let a = args[i]
        guard a.hasPrefix("--") else { fail("unexpected argument \(a)") }
        let key = String(a.dropFirst(2))
        if i + 1 < args.count, !args[i + 1].hasPrefix("--") { d[key] = args[i + 1]; i += 2 } else { d[key] = ""; i += 1 }
    }
    return d
}

func jobFromFlags(_ f: [String: String]) -> [String: Any] {
    let rename = ["panel-out": "panelOut"]
    var j: [String: Any] = [:]
    for (k, v) in f { j[rename[k] ?? k] = v }
    return j
}

let argv = Array(CommandLine.arguments.dropFirst())
guard let cmd = argv.first else { fail("usage: screen-occupancy calibrate|classify|batch|policy|--self-test (see README.md)") }
switch cmd {
case "--self-test", "self-test":
    let (passed, lines) = OccupancySelfTest.run()
    lines.forEach { print($0) }
    exit(passed ? 0 : 1)
case "policy":
    print(OccupancyJSON.encode(OccupancyV3.policy()))
case "calibrate":
    let f = flags(Array(argv.dropFirst()))
    let r = runCalibrate(jobFromFlags(f))
    print(OccupancyJSON.encode(r))
    exit((r.first { $0.0 == "ok" }?.1 as? Bool) == true ? 0 : 1)
case "classify":
    let f = flags(Array(argv.dropFirst()))
    let r = runClassify(jobFromFlags(f))
    print(OccupancyJSON.encode(r))
    exit((r.first { $0.0 == "ok" }?.1 as? Bool) == true ? 0 : 1)
case "batch":
    let f = flags(Array(argv.dropFirst()))
    guard let path = f["jobs"] else { fail("batch needs --jobs FILE|-") }
    let text: String
    if path == "-" { text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? "" }
    else { guard let t = try? String(contentsOfFile: path, encoding: .utf8) else { fail("cannot read \(path)") }; text = t }
    for line in text.split(separator: "\n") where !line.trimmingCharacters(in: .whitespaces).isEmpty {
        guard let obj = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else {
            print(OccupancyJSON.encode([("ok", false), ("error", "bad-job-json")] as [(String, Any)])); continue
        }
        let r = (obj["op"] as? String) == "calibrate" ? runCalibrate(obj) : runClassify(obj)
        print(OccupancyJSON.encode(r))
        fflush(stdout)
    }
default:
    fail("unknown command \(cmd)")
}
