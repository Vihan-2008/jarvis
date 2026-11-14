// jarvis-menu: JARVIS's icon in the Mac's menu bar, and its keyboard shortcuts that work from any app.
//
// It decides nothing itself. When its menu or a shortcut is used it prints one word on a line ("open", "talk",
// "dictate", "stop" or "quit"), and JARVIS's background helper (jcc/tray.py), which started it and reads those lines,
// does the thing. It reads lines too: "dictating 1" or "dictating 0" changes what the menu offers. It stops when
// whoever started it closes its input or goes away.
//
// The shortcuts are Control+Option with a letter, the Mac's counterpart of Ctrl+Alt on Windows. Each has a few choices,
// best first: another app may already own one, and then the next is tried. They are registered the way macOS lets any
// app register a shortcut (no permission is needed, and no key that is typed is ever seen by this program).
//
// First it prints one line of JSON saying what it could set up: {"icon": true, "keys": {"open": "Control+Option+J", ...}}.
//
//   jarvis-menu [--no-icon] [--no-keys]
// Build:  swiftc -O -o jarvis-menu menu_bar.swift

import AppKit
import Carbon.HIToolbox

func say(_ word: String) {
    print(word)
    fflush(stdout)
}

struct Shortcut {
    let name: String
    let choices: [(label: String, key: Int)]
}

let shortcuts: [Shortcut] = [
    Shortcut(name: "open", choices: [("Control+Option+J", kVK_ANSI_J)]),
    Shortcut(name: "stop", choices: [("Control+Option+Delete", kVK_Delete)]),
    Shortcut(name: "talk", choices: [("Control+Option+T", kVK_ANSI_T), ("Control+Option+K", kVK_ANSI_K), ("Control+Option+Space", kVK_Space)]),
    Shortcut(name: "dictate", choices: [("Control+Option+D", kVK_ANSI_D), ("Control+Option+Y", kVK_ANSI_Y), ("Control+Option+U", kVK_ANSI_U)]),
]

final class Menu: NSObject, NSApplicationDelegate {
    private var item: NSStatusItem?
    private var dictate: NSMenuItem?
    private var keys: [String: String] = [:]
    private let wantsIcon: Bool
    private let wantsKeys: Bool

    init(icon: Bool, keys: Bool) {
        wantsIcon = icon
        wantsKeys = keys
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if wantsKeys { claimShortcuts() }
        if wantsIcon { addIcon() }
        let told: [String: Any] = ["icon": item != nil, "keys": keys]
        if let data = try? JSONSerialization.data(withJSONObject: told, options: [.sortedKeys]), let line = String(data: data, encoding: .utf8) {
            say(line)
        }
        Thread.detachNewThread { [weak self] in self?.listen() }
    }

    // ------------------------------------------------------------------ the shortcuts
    private func claimShortcuts() {
        var kind = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var pressed = EventHotKeyID()
            let status = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                           MemoryLayout<EventHotKeyID>.size, nil, &pressed)
            if status == noErr, pressed.id >= 1, Int(pressed.id) <= shortcuts.count {
                say(shortcuts[Int(pressed.id) - 1].name)
            }
            return noErr
        }, 1, &kind, nil, nil)
        for (index, shortcut) in shortcuts.enumerated() {
            for choice in shortcut.choices {
                var reference: EventHotKeyRef?
                let ident = EventHotKeyID(signature: OSType(0x4A525653), id: UInt32(index + 1))        // "JRVS"
                if RegisterEventHotKey(UInt32(choice.key), UInt32(controlKey | optionKey), ident, GetApplicationEventTarget(), 0, &reference) == noErr {
                    keys[shortcut.name] = choice.label
                    break
                }
            }
        }
    }

    // ------------------------------------------------------------------ the icon and its menu
    private func addIcon() {
        let made = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = made.button {
            var picture: NSImage?
            if #available(macOS 11.0, *) {
                picture = NSImage(systemSymbolName: "waveform.circle", accessibilityDescription: "JARVIS")
            }
            if let picture = picture {
                picture.isTemplate = true                       // drawn in the menu bar's own colour, light or dark
                button.image = picture
            } else {
                button.title = "J"
            }
            button.toolTip = "JARVIS"
            button.setAccessibilityTitle("JARVIS")
        }
        let menu = NSMenu()
        menu.addItem(entry("Open JARVIS", "open", #selector(open)))
        menu.addItem(entry("Talk to JARVIS", "talk", #selector(talk)))
        let dictation = entry("Dictate into any app", "dictate", #selector(startDictation))
        menu.addItem(dictation)
        dictate = dictation
        menu.addItem(entry("Stop everything JARVIS is doing", "stop", #selector(stop)))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(entry("Hide this icon until JARVIS is next opened", "", #selector(quit)))
        made.menu = menu
        item = made
    }

    private func entry(_ title: String, _ shortcut: String, _ action: Selector) -> NSMenuItem {
        let label = keys[shortcut].map { title + "    " + $0 } ?? title
        let made = NSMenuItem(title: label, action: action, keyEquivalent: "")
        made.target = self
        return made
    }

    @objc private func open() { say("open") }
    @objc private func talk() { say("talk") }
    @objc private func startDictation() { say("dictate") }
    @objc private func stop() { say("stop") }
    @objc private func quit() {
        say("quit")
        NSApp.terminate(nil)
    }

    // ------------------------------------------------------------------ what JARVIS tells it
    private func listen() {
        while let line = readLine(strippingNewline: true) {
            let words = line.split(separator: " ")
            if words.count == 2, words[0] == "dictating" {
                let on = words[1] == "1"
                DispatchQueue.main.async { [weak self] in
                    guard let self = self, let dictation = self.dictate else { return }
                    let title = on ? "Finish dictating" : "Dictate into any app"
                    dictation.title = self.keys["dictate"].map { title + "    " + $0 } ?? title
                }
            }
        }
        exit(0)                                                 // the input was closed: whoever started this has gone
    }
}

signal(SIGPIPE, SIG_DFL)
let arguments = CommandLine.arguments.dropFirst()
let app = NSApplication.shared
let menu = Menu(icon: !arguments.contains("--no-icon"), keys: !arguments.contains("--no-keys"))
app.delegate = menu
app.setActivationPolicy(.accessory)                             // no Dock icon and no menu of its own: only the menu-bar icon
app.run()
