import Foundation

/// Deterministic JSON text for ordered key lists [(String, Any)], arrays, strings, numbers, Bool, nil.
public enum OccupancyJSON {
    public static func encode(_ v: Any?) -> String {
        var s = ""
        write(v, &s)
        return s
    }

    static func write(_ v: Any?, _ s: inout String) {
        switch v {
        case nil: s += "null"
        case is NSNull: s += "null"
        case let x as Bool: s += x ? "true" : "false"
        case let x as Int: s += String(x)
        case let x as Double: s += x.isFinite ? (x == x.rounded() && abs(x) < 1e15 ? String(format: "%.1f", x) : "\(x)") : "null"
        case let x as String: writeString(x, &s)
        case let x as [(String, Any)]:
            s += "{"
            for (i, (k, val)) in x.enumerated() { if i > 0 { s += ", " }; writeString(k, &s); s += ": "; write(val, &s) }
            s += "}"
        case let x as [(String, Any?)]:
            s += "{"
            for (i, (k, val)) in x.enumerated() { if i > 0 { s += ", " }; writeString(k, &s); s += ": "; write(val, &s) }
            s += "}"
        case let x as [Any]:
            s += "["
            for (i, val) in x.enumerated() { if i > 0 { s += ", " }; write(val, &s) }
            s += "]"
        case let x as [Any?]:
            s += "["
            for (i, val) in x.enumerated() { if i > 0 { s += ", " }; write(val, &s) }
            s += "]"
        default: writeString(String(describing: v!), &s)
        }
    }

    static func writeString(_ x: String, _ s: inout String) {
        s += "\""
        for ch in x.unicodeScalars {
            switch ch {
            case "\"": s += "\\\""
            case "\\": s += "\\\\"
            case "\n": s += "\\n"
            case "\t": s += "\\t"
            default:
                if ch.value < 0x20 { s += String(format: "\\u%04x", ch.value) } else { s.unicodeScalars.append(ch) }
            }
        }
        s += "\""
    }

    public static func calibrationJSON(_ c: OccupancyV3.Calibration, extra: [(String, Any)] = []) -> [(String, Any)] {
        func arr(_ v: SIMD3<Double>) -> [Any] { [v.x, v.y, v.z] }
        return [("version", OccupancyV3.version), ("emptyRef", [arr(c.emptyRef[0]), arr(c.emptyRef[1])]),
                ("contrast", c.contrast), ("boundarySharpness", c.boundarySharpness),
                ("fillRef", [("white", arr(c.whiteRef)), ("black", arr(c.blackRef))] as [(String, Any)]),
                ("policy", OccupancyV3.policy())] + extra
    }

    /// Reads a calibration written by this tool or by Python's calibrate() (json.dumps of its dict).
    public static func calibration(from obj: [String: Any]) -> OccupancyV3.Calibration? {
        func v3(_ a: Any?) -> SIMD3<Double>? {
            guard let a = a as? [Any], a.count == 3 else { return nil }
            let d = a.compactMap { ($0 as? NSNumber)?.doubleValue }
            return d.count == 3 ? SIMD3(d[0], d[1], d[2]) : nil
        }
        guard let e = obj["emptyRef"] as? [Any], e.count == 2, let e0 = v3(e[0]), let e1 = v3(e[1]),
              let contrast = (obj["contrast"] as? NSNumber)?.doubleValue,
              let fill = obj["fillRef"] as? [String: Any], let w = v3(fill["white"]), let b = v3(fill["black"]) else { return nil }
        // v3.1: a missing, boolean or non-numeric boundarySharpness is read as NaN, so classify abstains on the whole frame
        // (= Python _sharpness_reference_ok).
        var sharp = Double.nan
        if let n = obj["boundarySharpness"] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() { sharp = n.doubleValue }
        return OccupancyV3.Calibration(emptyRef: [e0, e1], contrast: contrast, boundarySharpness: sharp, whiteRef: w, blackRef: b)
    }
}
