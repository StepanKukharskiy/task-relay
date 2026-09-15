import AppKit
import Foundation

final class RelayApp: NSObject, NSApplicationDelegate {
    let configuration: [String: String] = {
        let url = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/runtime.json")
        guard let data = try? Data(contentsOf: url),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return [:] }
        return config
    }()
    var root: URL { URL(fileURLWithPath: configuration["root"] ?? Bundle.main.bundleURL.deletingLastPathComponent().path) }
    var child: Process?
    var item: NSStatusItem!
    var status: NSMenuItem!
    var detail: NSMenuItem!
    var timer: Timer?
    var nextStart = Date.distantPast
    var quitting = false
    var started = false
    var signals: [DispatchSourceSignal] = []
    var folder: URL { URL(fileURLWithPath: configuration["messages"] ?? root.appendingPathComponent("private/messages-pilot").path) }
    var pauseFile: URL { folder.appendingPathComponent("paused") }
    var paused: Bool { FileManager.default.fileExists(atPath: pauseFile.path) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        start()
    }

    func start() {
        guard !started else { return }
        started = true
        FileHandle.standardError.write(Data("Messages Relay launcher started\n".utf8))
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let url = Bundle.main.url(forResource: "MenuBarTemplate", withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            image.size = NSSize(width: 20, height: 20)
            image.isTemplate = true
            item.button?.image = image
            item.button?.imagePosition = .imageOnly
        } else {
            item.button?.title = "MR"
        }
        item.button?.toolTip = "Messages Relay"
        let menu = NSMenu()
        status = NSMenuItem(title: "Messages Relay is starting…", action: nil, keyEquivalent: "")
        detail = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        menu.addItem(status)
        menu.addItem(detail)
        menu.addItem(.separator())
        for (title, action) in [("Start / Restart", #selector(restart)),
                                ("Pause", #selector(pause)),
                                ("Full Disk Access Settings…", #selector(permissions)),
                                ("Show Relay Folder", #selector(showFolder))] {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: "")
            entry.target = self
            menu.addItem(entry)
        }
        item.menu = menu
        for number in [SIGTERM, SIGINT] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { [weak self] in
                self?.quitting = true
                NSApplication.shared.terminate(nil)
            }
            source.resume()
            signals.append(source)
        }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.tick() }
        tick()
    }

    func launch() {
        let configURL = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/runtime.json")
        guard let data = try? Data(contentsOf: configURL),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let python = config["python"] else {
            status.title = "Messages Relay needs repair"
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", "task_relay.messages_pilot", "--background"]
        process.currentDirectoryURL = root
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["PYTHONUNBUFFERED"] = "1"
        for (key, setting) in [("TASK_RELAY_DATA_DIR", "data"), ("TASK_RELAY_WORKSPACE_DIR", "workspaces"), ("TASK_RELAY_GENERATED_DIR", "generated")] {
            if let value = configuration[setting] { env[key] = value }
        }
        process.environment = env
        process.standardInput = FileHandle.nullDevice
        // launchd owns private, bounded-by-low-volume status logs. No prompts or keys are logged.
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.child = nil
                self?.nextStart = Date().addingTimeInterval(15)
                self?.status.title = "Messages Relay needs attention"
                self?.detail.title = "Enable Messages Relay in Full Disk Access settings"
            }
        }
        do {
            try process.run()
            child = process
        } catch {
            status.title = "Messages Relay needs access"
            detail.title = "Enable Messages Relay in Full Disk Access settings"
            nextStart = Date().addingTimeInterval(15)
        }
    }

    func tick() {
        if quitting { return }
        if paused {
            status.title = "Messages Relay is paused"
            detail.title = "Choose Start / Restart to resume"
            return
        }
        if child == nil && Date() >= nextStart { launch() }
        let url = folder.appendingPathComponent("health.json")
        if let data = try? Data(contentsOf: url),
           let health = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            let state = health["status"] as? String ?? "starting"
            let updated = health["updated_at"] as? Double ?? 0
            let healthPID = health["pid"] as? Int ?? -1
            if state == "running" && Date().timeIntervalSince1970 - updated < 20 && child?.isRunning == true && healthPID == Int(child!.processIdentifier) {
                status.title = "Messages Relay is running"
                detail.title = "Gemini and Codex · Terminal can be closed"
            } else if state == "needs_attention" {
                status.title = "Messages Relay needs attention"
                detail.title = String((health["detail"] as? String ?? "Check relay logs").prefix(130))
            } else {
                status.title = "Messages Relay is starting…"
                detail.title = "Waiting for the Messages connection"
            }
        }
    }

    @objc func restart() {
        try? FileManager.default.removeItem(at: pauseFile)
        if let child, child.isRunning { child.terminate() }
        nextStart = Date()
        tick()
    }

    @objc func pause() {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? Data().write(to: pauseFile)
        child?.terminate()
        tick()
    }

    @objc func permissions() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!)
    }

    @objc func showFolder() {
        NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL])
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        timer?.invalidate()
        guard let child, child.isRunning else { return }
        child.terminate()
        let deadline = Date().addingTimeInterval(7)
        while child.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
    }
}

let app = NSApplication.shared
let delegate = RelayApp()
app.delegate = delegate
app.setActivationPolicy(.accessory)
// Direct launchd starts must not depend solely on a LaunchServices launch event.
delegate.start()
withExtendedLifetime(delegate) {
    app.run()
}
