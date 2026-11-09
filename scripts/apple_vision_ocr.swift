import Foundation
import Vision
import ImageIO

struct OCRResult: Codable {
    let file: String
    let text: [String]
}

guard CommandLine.arguments.count > 1 else {
    exit(1)
}

let paths = Array(CommandLine.arguments.dropFirst())
var results: [OCRResult] = []

for path in paths {
    let url = CFURLCreateWithFileSystemPath(kCFAllocatorDefault, path as CFString, .cfurlposixPathStyle, false)!
    guard let source = CGImageSourceCreateWithURL(url, nil),
          let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        results.append(OCRResult(file: path, text: []))
        continue
    }
    
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .fast
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    try? handler.perform([request])
    
    let strings = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    results.append(OCRResult(file: path, text: strings))
}

let encoder = JSONEncoder()
if let data = try? encoder.encode(results), let jsonString = String(data: data, encoding: .utf8) {
    print(jsonString)
}
