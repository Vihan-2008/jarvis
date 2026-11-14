// The program inside JARVIS.app: it starts JARVIS from its install folder with the Python the installer chose.
//
// JARVIS.app used to hold a small shell script instead. macOS treats an app whose program is a script poorly: what it
// is allowed (the Documents folder the notes are in, the microphone) is not asked for or kept the way it is for a real
// program, so JARVIS could fail when opened from its icon and work when typed in Terminal (which had been allowed).
// This is a real program, signed on the Mac it is installed on, so macOS asks for JARVIS by name and remembers.
//
// What it does: reads the install folder from Contents/Resources/install-dir (written by the installer), reads the
// Python to use from <install folder>/.python, sends anything printed to ~/Library/Logs/JARVIS/launcher.log, and then
// becomes "python -m jcc.desktop" (the same process, so macOS keeps counting it as JARVIS).
//
// Build:  swiftc -O -o jarvis-launcher launcher.swift

import Foundation

func fail(_ words: String) -> Never {
    FileHandle.standardError.write(("JARVIS could not start: " + words + "\n").data(using: .utf8)!)
    let script = "on run argv\ndisplay alert \"JARVIS\" message (item 1 of argv) as critical\nend run"
    let alert = Process()
    alert.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    alert.arguments = ["-e", script, words]                        // (the words are an argument, never part of the script)
    try? alert.run()
    alert.waitUntilExit()
    exit(1)
}

func read(_ path: String) -> String {
    ((try? String(contentsOfFile: path, encoding: .utf8)) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
}

let resources = Bundle.main.resourcePath ?? ""
let folder = read(resources + "/install-dir")
let files = FileManager.default
if folder.isEmpty || !files.fileExists(atPath: folder + "/jcc/__init__.py") {
    fail("its files were not found\(folder.isEmpty ? "" : " in \(folder)"). Run the JARVIS installer again.")
}

// What is printed goes to a log of its own, so a JARVIS that does not start can say why.
let logs = NSHomeDirectory() + "/Library/Logs/JARVIS"
try? files.createDirectory(atPath: logs, withIntermediateDirectories: true)
let log = open(logs + "/launcher.log", O_WRONLY | O_CREAT | O_APPEND, 0o644)
if log >= 0 {
    dup2(log, 1)
    dup2(log, 2)
    print("--- \(Date()) JARVIS opened from its app, in \(folder)")
}

var python = read(folder + "/.python")
if python.isEmpty || !files.isExecutableFile(atPath: python) {
    for candidate in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"]
        where files.isExecutableFile(atPath: candidate) {
        python = candidate
        break
    }
}
if python.isEmpty || !files.isExecutableFile(atPath: python) {
    fail("Python 3.11 or newer was not found. Install it from python.org, then run the JARVIS installer again.")
}

guard files.changeCurrentDirectoryPath(folder) else { fail("its folder \(folder) could not be opened.") }
setenv("PYTHONPATH", folder, 1)
setenv("PYTHONUNBUFFERED", "1", 1)
let passed = CommandLine.arguments.dropFirst().filter { !$0.hasPrefix("-psn_") }      // (old macOS adds a process number)
let argv = [python, "-m", "jcc.desktop"] + passed
var cArgs = argv.map { strdup($0) } + [nil]
execv(python, &cArgs)
fail("Python could not be started (\(String(cString: strerror(errno)))).")
