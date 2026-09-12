// Local face rectangles guide safe cropping; no recognition or face modification.
import Foundation
import Vision

let folder = URL(fileURLWithPath: CommandLine.arguments[1])
let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
    .filter { $0.pathExtension.lowercased() == "jpg" }.sorted { $0.path < $1.path }
var output: [String: [[Double]]] = [:]
for file in files {
    try autoreleasepool {
        let request = VNDetectFaceRectanglesRequest()
        try VNImageRequestHandler(url: file, options: [:]).perform([request])
        output[file.deletingPathExtension().lastPathComponent] = (request.results ?? []).map {
            let b = $0.boundingBox
            return [Double(b.minX), Double(1 - b.maxY), Double(b.width), Double(b.height)]
        }
    }
}
let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys, .prettyPrinted])
try data.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
print("Detected face rectangles in \(output.count) source images")
