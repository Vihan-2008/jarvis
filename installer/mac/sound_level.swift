// jarvis-sound-level: how loud the Mac's own sound is, and nothing else.
//
// JARVIS uses this to tell a film, a video or music playing on the Mac from its owner speaking (jcc/pcsound.py): sound
// at the microphone that rises and falls in step with what the Mac plays is the Mac's own, and is dropped.
//
// It listens to what the Mac plays through ScreenCaptureKit (macOS 13 or newer; the Screen Recording permission) and
// prints one line "ready", then one number from 0 to 1 every fiftieth of a second: the loudest moment in that time.
// Nothing it hears is kept, written or sent anywhere, and no picture of the screen is used. It stops when whoever
// started it closes its input or goes away.
//
// Build:  swiftc -O -o jarvis-sound-level sound_level.swift
// Exit codes: 2 = macOS is too old, 3 = the listening stopped, 4 = not allowed or nothing to listen to.

import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

func fail(_ words: String, _ code: Int32) -> Never {
    FileHandle.standardError.write((words + "\n").data(using: .utf8)!)
    exit(code)
}

@available(macOS 13.0, *)
final class Meter: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private let lock = NSLock()
    private var loudest: Float = 0
    private let sounds = DispatchQueue(label: "jarvis.sound-level.sounds")

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else { fail("no screen to attach to", 4) }
        let settings = SCStreamConfiguration()
        settings.capturesAudio = true
        settings.excludesCurrentProcessAudio = true
        settings.sampleRate = 16000
        settings.channelCount = 1
        settings.width = 2                                    // the picture is not wanted: as small and as rare as it can be
        settings.height = 2
        settings.minimumFrameInterval = CMTime(value: 2, timescale: 1)
        settings.queueDepth = 3
        let made = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: settings, delegate: self)
        try made.addStreamOutput(self, type: .audio, sampleHandlerQueue: sounds)
        try await made.startCapture()
        stream = made
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid, let block = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        var length = 0
        var start: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &start) == kCMBlockBufferNoErr,
              let bytes = start, length >= 4 else { return }
        var peak: Float = 0
        bytes.withMemoryRebound(to: Float32.self, capacity: length / 4) { samples in     // ScreenCaptureKit gives 32-bit float sound
            for index in 0..<(length / 4) {
                let size = abs(samples[index])
                if size > peak { peak = size }
            }
        }
        lock.lock()
        if peak > loudest { loudest = peak }
        lock.unlock()
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail("listening stopped: \(error.localizedDescription)", 3)
    }

    func take() -> Float {
        lock.lock()
        defer { lock.unlock() }
        let level = min(1, loudest)
        loudest = 0
        return level
    }
}

@available(macOS 13.0, *)
func listen() -> Never {
    let meter = Meter()
    let ticks = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "jarvis.sound-level.ticks"))
    Task {
        do {
            try await meter.start()
        } catch {
            fail("could not start: \(error.localizedDescription)", 4)
        }
        print("ready")
        ticks.schedule(deadline: .now() + .milliseconds(20), repeating: .milliseconds(20))
        ticks.setEventHandler { print(String(format: "%.4f", meter.take())) }
        ticks.resume()
    }
    DispatchQueue.global().async {                            // stop when the input is closed
        while let _ = readLine(strippingNewline: true) {}
        exit(0)
    }
    dispatchMain()
}

setvbuf(stdout, nil, _IOLBF, 0)
signal(SIGPIPE, SIG_DFL)                                      // whoever was reading has gone: stop

if #available(macOS 13.0, *) {
    listen()
} else {
    fail("macOS 13 or newer is needed", 2)
}
