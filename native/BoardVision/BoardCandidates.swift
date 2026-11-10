import Foundation
import Vision
import ImageIO
import CoreImage
import UniformTypeIdentifiers

// Adapted from ../blackjack-practice/native/RecognitionLab/CardRecognizer.swift:
// ImageIO loading, VNDetectRectanglesRequest, CI perspective correction and JSON reporting.
// No OCR/card-rank logic is reused. Rectangles are NOT recognized chessboards.
struct Point: Codable { let x: Double; let y: Double }
struct Candidate: Codable { let corners: [Point]; let rectangleConfidence: Float; let normalizedImage: String }
struct Report: Codable { let width: Int; let height: Int; let candidates: [Candidate] }
do {
    guard CommandLine.arguments.count == 3 else { throw NSError(domain:"BoardVision",code:1,userInfo:[NSLocalizedDescriptionKey:"Usage: board-candidates INPUT OUTPUT_DIRECTORY"]) }
    let path = CommandLine.arguments[1], directory = CommandLine.arguments[2]
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath:path) as CFURL,nil), let image = CGImageSourceCreateImageAtIndex(source,0,nil) else { throw NSError(domain:"BoardVision",code:2,userInfo:[NSLocalizedDescriptionKey:"Unreadable image"]) }
    let request = VNDetectRectanglesRequest()
    request.maximumObservations = 24; request.minimumConfidence = 0.5
    request.minimumAspectRatio = 0.35; request.maximumAspectRatio = 1
    request.minimumSize = 0.15; request.quadratureTolerance = 45
    try VNImageRequestHandler(cgImage:image).perform([request])
    let ci = CIImage(cgImage:image), context = CIContext(options:[.useSoftwareRenderer:false])
    func point(_ p: CGPoint) -> CIVector { CIVector(x:p.x * CGFloat(image.width),y:p.y * CGFloat(image.height)) }
    try FileManager.default.createDirectory(atPath:directory,withIntermediateDirectories:true)
    var candidates: [Candidate] = []
    for (index,r) in (request.results ?? []).enumerated() {
        let corrected = ci.applyingFilter("CIPerspectiveCorrection",parameters:["inputTopLeft":point(r.topLeft),"inputTopRight":point(r.topRight),"inputBottomRight":point(r.bottomRight),"inputBottomLeft":point(r.bottomLeft)])
        guard let crop = context.createCGImage(corrected,from:corrected.extent) else { continue }
        let output = URL(fileURLWithPath:directory).appendingPathComponent("candidate-\(index).png")
        guard let destination = CGImageDestinationCreateWithURL(output as CFURL,UTType.png.identifier as CFString,1,nil) else { continue }
        CGImageDestinationAddImage(destination,crop,nil)
        guard CGImageDestinationFinalize(destination) else { continue }
        candidates.append(Candidate(corners:[r.topLeft,r.topRight,r.bottomRight,r.bottomLeft].map { Point(x:Double($0.x)*Double(image.width),y:(1-Double($0.y))*Double(image.height)) },rectangleConfidence:r.confidence,normalizedImage:output.path))
    }
    let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
    print(String(decoding:try encoder.encode(Report(width:image.width,height:image.height,candidates:candidates)),as:UTF8.self))
} catch { FileHandle.standardError.write(Data("Board candidate extraction failed: \(error)\n".utf8)); exit(1) }
