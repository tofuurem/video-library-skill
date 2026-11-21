// Sounds in an audio file (Apple SoundAnalysis, built-in classifier, 303 classes) → JSON on stdout:
// [{"s": start, "e": end, "top": [["speech", 0.71], ...]}, ...] — 3 s windows, no overlap.
import Foundation
import SoundAnalysis
import AVFoundation
final class Obs: NSObject, SNResultsObserving {
    var rows: [[String: Any]] = []
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let r = result as? SNClassificationResult else { return }
        let top = r.classifications.prefix(4).filter { $0.confidence > 0.2 }.map { [$0.identifier, (Double($0.confidence) * 100).rounded() / 100] as [Any] }
        rows.append(["s": (r.timeRange.start.seconds * 10).rounded() / 10, "e": ((r.timeRange.start.seconds + r.timeRange.duration.seconds) * 10).rounded() / 10, "top": top])
    }
}
let analyzer = try SNAudioFileAnalyzer(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let req = try SNClassifySoundRequest(classifierIdentifier: .version1)
req.windowDuration = CMTime(seconds: 3, preferredTimescale: 48000)
req.overlapFactor = 0.0
let obs = Obs()
try analyzer.add(req, withObserver: obs)
analyzer.analyze()
let data = try JSONSerialization.data(withJSONObject: obs.rows)
FileHandle.standardOutput.write(data)
