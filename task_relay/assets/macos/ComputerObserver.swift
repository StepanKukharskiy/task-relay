// Native bounded Safari observation/session helper. No arbitrary input or cookie APIs.
import AppKit
import ApplicationServices
import ScreenCaptureKit
import ImageIO
import UniformTypeIdentifiers
import Darwin

let protocolID = "relay.computer-observer.v1"
struct Blocked: Error { let code: String; init(_ code: String) { self.code = code } }

func attribute(_ element: AXUIElement, _ key: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, key as CFString, &value) == .success ? value : nil
}
func string(_ element: AXUIElement, _ key: String) -> String? {
    attribute(element, key) as? String
}
func children(_ element: AXUIElement) -> [AXUIElement] {
    (attribute(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []
}
func frame(_ element: AXUIElement) -> CGRect? {
    guard let p = attribute(element, kAXPositionAttribute), let s = attribute(element, kAXSizeAttribute),
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero, size = CGSize.zero
    guard AXValueGetValue(p as! AXValue, .cgPoint, &point),
          AXValueGetValue(s as! AXValue, .cgSize, &size), size.width > 0, size.height > 0 else { return nil }
    return CGRect(origin: point, size: size)
}
func sameFrame(_ a: CGRect, _ b: CGRect) -> Bool {
    abs(a.minX-b.minX) < 2 && abs(a.minY-b.minY) < 2 && abs(a.width-b.width) < 2 && abs(a.height-b.height) < 2
}
func unlocked() -> Bool {
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
    return (session["CGSSessionScreenIsLocked"] as? Bool) != true &&
        (session[kCGSessionOnConsoleKey as String] as? Bool) == true
}
func status() -> [String: Any] {
    ["accessibility": AXIsProcessTrusted(), "screen_recording": CGPreflightScreenCaptureAccess(),
     "session_unlocked": unlocked(), "minimum_macos": "14.0",
     "ready": AXIsProcessTrusted() && CGPreflightScreenCaptureAccess() && unlocked(),
     "operations": ["status", "windows", "observe", "request-permissions"],
     "permission_prompted": false]
}
func requireAccess() throws {
    guard unlocked() else { throw Blocked("interactive_unlocked_session_required") }
    guard AXIsProcessTrusted() else { throw Blocked("accessibility_permission_required") }
    guard CGPreflightScreenCaptureAccess() else { throw Blocked("screen_recording_permission_required") }
}
func documentURL(_ document: AXUIElement) -> String? {
    // Safari exposes the loaded URL on its AXWebArea, not reliably on AXWindow.
    if let url = attribute(document, kAXURLAttribute) as? URL { return url.absoluteString }
    return string(document, kAXURLAttribute)
}
func webArea(_ window: AXUIElement, bounds: CGRect) throws -> AXUIElement {
    var queue = [window], result: [AXUIElement] = [], count = 0
    while !queue.isEmpty {
        let e = queue.removeFirst(); count += 1
        if count > 1500 { throw Blocked("window_accessibility_tree_exceeds_limit") }
        if (attribute(e, "AXHidden") as? Bool) == true { continue }
        let role = string(e, kAXRoleAttribute) ?? ""
        if role == "AXSheet" || role == "AXDialog" { throw Blocked("dialog_requires_user") }
        if role == "AXWebArea" {
            if let rect = frame(e), rect.intersects(bounds) { result.append(e) }
            continue // Never walk frames or another web document.
        }
        // Prune editable controls; do not inspect their values.
        if role == "AXTextField" || role == "AXTextArea" || role == "AXComboBox" { continue }
        queue += children(e)
    }
    guard result.count == 1 else { throw Blocked("active_web_document_not_unique") }
    return result[0]
}
struct Reading {
    var text: String
    var truncated: Bool
    var captureAllowed: Bool
}
func readDocument(_ document: AXUIElement, bounds: CGRect) -> Reading {
    var queue = [document], lines: [String] = [], bytes = 0, count = 0
    var truncated = false, captureAllowed = true
    while !queue.isEmpty {
        let e = queue.removeFirst(); count += 1
        if count > 4000 { truncated = true; break }
        if (attribute(e, "AXHidden") as? Bool) == true { continue }
        let role = string(e, kAXRoleAttribute) ?? ""
        let visible = frame(e).map { $0.intersects(bounds) } ?? false
        if role == "AXWebArea" && !CFEqual(e, document) {
            if visible { captureAllowed = false }
            continue
        }
        // Input values, including password/OTP/search/composer content, never enter text.
        if ["AXTextField", "AXTextArea", "AXComboBox", "AXSecureTextField"].contains(role) {
            if visible { captureAllowed = false }
            continue
        }
        if visible && role == "AXStaticText", let text = string(e, kAXValueAttribute), !text.isEmpty {
            let length = text.utf8.count + 1
            if bytes + length > 24000 { truncated = true; break }
            lines.append(text); bytes += length
        }
        queue += children(e)
    }
    return Reading(text: lines.joined(separator: "\n"), truncated: truncated, captureAllowed: captureAllowed)
}

func actionNames(_ element: AXUIElement) -> [String] {
    var names: CFArray?
    guard AXUIElementCopyActionNames(element, &names) == .success else { return [] }
    return names as? [String] ?? []
}
func parentElement(_ element: AXUIElement) -> AXUIElement? {
    guard let parent = attribute(element, kAXParentAttribute), CFGetTypeID(parent) == AXUIElementGetTypeID() else { return nil }
    return (parent as! AXUIElement)
}
func addressField(_ window: AXUIElement) throws -> AXUIElement {
    var queue = [window], found: [AXUIElement] = [], count = 0
    while !queue.isEmpty {
        let element = queue.removeFirst(); count += 1
        if count > 1500 { throw Blocked("window_accessibility_tree_exceeds_limit") }
        if string(element, kAXRoleAttribute) == "AXWebArea" { continue }
        if string(element, kAXIdentifierAttribute) == "WEB_BROWSER_ADDRESS_AND_SEARCH_FIELD",
           string(element, kAXRoleAttribute) == "AXTextField" { found.append(element) }
        queue += children(element)
    }
    guard found.count == 1 else { throw Blocked("unique_safari_address_field_required") }
    return found[0]
}

func selectedTab(_ window: AXUIElement) throws -> AXUIElement {
    var queue = [window], found: [AXUIElement] = [], count = 0
    while !queue.isEmpty {
        let element = queue.removeFirst(); count += 1
        if count > 1500 { throw Blocked("window_accessibility_tree_exceeds_limit") }
        if string(element, kAXRoleAttribute) == "AXWebArea" { continue }
        if let id = string(element, kAXIdentifierAttribute), id.hasPrefix("TabBarTab?"),
           id.contains("isActive=true") { found.append(element); continue }
        queue += children(element)
    }
    guard found.count == 1 else { throw Blocked("show_safari_tab_bar_for_session") }
    return found[0]
}

// Non-activating ownership panel: Safari retains focus. Controls are terminal
// for this attempt, including Pause; no silent continuation after user takeover.
@MainActor final class SessionOwnership: NSObject, NSWindowDelegate {
    let panel: NSPanel
    let status = NSTextField(labelWithString: "Observing selected Safari window")
    let event: URL
    let cancelPath: String?
    var halted = false
    init(label: String, eventPath: String, cancelPath: String? = nil) throws {
        self.cancelPath = cancelPath
        event = URL(fileURLWithPath: eventPath)
        guard event.isFileURL, eventPath.hasPrefix("/"), !FileManager.default.fileExists(atPath: eventPath) else {
            throw Blocked("invalid_ownership_event_path")
        }
        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 430, height: 126),
                        styleMask: [.titled, .nonactivatingPanel], backing: .buffered, defer: false)
        super.init()
        panel.title = "Relay owns this Safari session"
        panel.level = .floating; panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isReleasedWhenClosed = false; panel.delegate = self
        let owner = NSTextField(labelWithString: String(label.prefix(160)))
        owner.frame = NSRect(x: 14, y: 90, width: 400, height: 22)
        owner.lineBreakMode = .byTruncatingTail
        status.frame = NSRect(x: 14, y: 61, width: 400, height: 22)
        panel.contentView?.addSubview(owner); panel.contentView?.addSubview(status)
        for (index, title) in ["Pause", "Stop", "Take over"].enumerated() {
            let button = NSButton(title: title, target: self, action: #selector(control(_:)))
            button.tag = index; button.frame = NSRect(x: 14 + index * 134, y: 16, width: 126, height: 30)
            panel.contentView?.addSubview(button)
        }
        if let screen = NSScreen.main {
            panel.setFrameTopLeftPoint(NSPoint(x: screen.visibleFrame.maxX - 450, y: screen.visibleFrame.maxY - 24))
        }
        panel.orderFrontRegardless()
    }
    @objc func control(_ sender: NSButton) {
        guard !halted else { return }
        halted = true
        let kind = ["pause", "stop", "takeover"][sender.tag]
        status.stringValue = "Stopped — " + sender.title + "; explicit recovery required"
        do {
            let data = try JSONSerialization.data(withJSONObject: ["kind": kind, "created_at": ISO8601DateFormatter().string(from: Date())])
            try data.write(to: event, options: [.withoutOverwriting])
            let handle = try FileHandle(forWritingTo: event); try handle.synchronize(); try handle.close()
        } catch {
            status.stringValue = "Stopped — control receipt failed; reconcile session"
            // Still fail closed in this native process even if the host cannot
            // persist the user's decision. It must never perform another action.
        }
    }
    func update(_ operation: String) throws {
        guard !halted, !FileManager.default.fileExists(atPath: event.path),
              cancelPath.map({ !FileManager.default.fileExists(atPath: $0) }) ?? true else { throw Blocked("session_ownership_released") }
        status.stringValue = operation
    }
}

// Kernel-backed identity avoids AppKit's transient application discovery cache.
// PID alone is insufficient: include exact start time and executable identity.
struct ScriptingProcessIdentity: Equatable {
    let pid: pid_t
    let seconds: UInt64
    let microseconds: UInt64
    let executable: String
    var launchID: String { String(format: "%llu.%06llu", seconds, microseconds) }
    static func read(_ pid: pid_t) -> ScriptingProcessIdentity? {
        guard pid > 0 else { return nil }
        var info = proc_bsdinfo()
        let size = MemoryLayout<proc_bsdinfo>.size
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, Int32(size)) == Int32(size),
              info.pbi_pid == UInt32(pid), info.pbi_start_tvsec > 0 else { return nil }
        var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
        guard proc_pidpath(pid, &path, UInt32(path.count)) > 0 else { return nil }
        return ScriptingProcessIdentity(pid: pid, seconds: info.pbi_start_tvsec,
            microseconds: info.pbi_start_tvusec, executable: String(cString: path))
    }
}

// Safari Apple Events are a separate, explicitly frozen transport. They never
// activate Safari, use Accessibility input, or relax the visual adapter's checks.
@MainActor final class SafariScriptingSession {
    var request: [String: Any]
    let urls: [String]
    let deadline: Date
    let owner: SessionOwnership
    let process: NSRunningApplication
    let processIdentity: ScriptingProcessIdentity
    let launchID: String
    var windowID = 0
    var javascriptAvailable: Bool?
    var token = ""
    var lastText = ""
    var calls = 0

    static func quote(_ value: String) -> String {
        "\"" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }
    static func script(_ body: String, phase: String = "event") throws -> NSAppleEventDescriptor {
        guard let script = NSAppleScript(source: "with timeout of 8 seconds\n tell application id \"com.apple.Safari\"\n" + body + "\n end tell\nend timeout") else {
            throw Blocked("safari_script_compilation_failed")
        }
        var error: NSDictionary?
        let value = script.executeAndReturnError(&error)
        if let error {
            let number = error[NSAppleScript.errorNumber] as? Int ?? 0
            if number == -1743 || number == -1744 { throw Blocked("safari_automation_permission_required") }
            if number == 8 { throw Blocked("safari_allow_javascript_from_apple_events_required") }
            if number == -1712 { throw Blocked("safari_apple_event_timeout_no_replay_" + phase) }
            throw Blocked("safari_apple_event_failed_" + String(number))
        }
        return value
    }
    static func application() throws -> NSRunningApplication {
        let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.Safari")
        guard apps.count == 1 else { throw Blocked("open_safari_once_before_background_research") }
        return apps[0]
    }
    static func createBlankDocument() throws {
        // Safari window creation can stall when dispatched synchronously by the
        // AppKit ownership-panel process. A separate OSA process owns this one
        // Apple Event; its bounded acknowledgement never contains page data.
        let source = """
        try
            with timeout of 8 seconds
                tell application id "com.apple.Safari"
                    make new document with properties {URL:"about:blank"}
                end tell
            end timeout
            return "relay:created"
        on error number n
            return "relay:error:" & n
        end try
        """
        let child = Process(), input = Pipe(), output = Pipe()
        child.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        child.arguments = ["-"]
        child.standardInput = input; child.standardOutput = output
        child.standardError = FileHandle.nullDevice
        let exited = DispatchSemaphore(value: 0)
        child.terminationHandler = { _ in exited.signal() }
        do { try child.run() } catch { throw Blocked("safari_window_create_process_failed") }
        do {
            try input.fileHandleForWriting.write(contentsOf: Data(source.utf8))
            try input.fileHandleForWriting.close()
        } catch {
            child.terminate()
            throw Blocked("safari_window_create_delivery_unknown_no_replay")
        }
        guard exited.wait(timeout: .now() + 12) == .success else {
            child.terminate()
            if exited.wait(timeout: .now() + 1) != .success { kill(child.processIdentifier, SIGKILL) }
            throw Blocked("safari_apple_event_timeout_no_replay_window_create")
        }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        guard child.terminationStatus == 0, data.count <= 128,
              let response = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw Blocked("safari_window_create_acknowledgement_unknown_no_replay")
        }
        if response == "relay:created" { return }
        if response.hasPrefix("relay:error:"), let number = Int(response.dropFirst("relay:error:".count)) {
            if number == -1743 || number == -1744 { throw Blocked("safari_automation_permission_required") }
            if number == -1712 { throw Blocked("safari_apple_event_timeout_no_replay_window_create") }
            throw Blocked("safari_apple_event_failed_" + String(number))
        }
        throw Blocked("safari_window_create_acknowledgement_unknown_no_replay")
    }
    static func status() throws -> [String: Any] {
        let app = try application()
        guard ScriptingProcessIdentity.read(app.processIdentifier) != nil else { throw Blocked("safari_process_identity_unavailable") }
        _ = try script("return count of windows", phase: "readiness")
        return ["ready": true, "automation": true, "session_unlocked": unlocked(),
                "transport": "safari-scripting", "scroll_requires_safari_javascript_setting": true]
    }
    init(_ input: [String: Any]) throws {
        guard let r = input["observation_request"] as? [String: Any],
              r["target"] as? [String: String] == ["mode": "new-scripting-window"],
              r["capture"] as? Bool == false,
              let allowed = input["allowed_urls"] as? [String], allowed.count > 0, allowed.count <= 10,
              Set(allowed).count == allowed.count, let url = r["expected_url"] as? String, allowed.contains(url),
              let seconds = input["max_seconds"] as? Int, seconds > 0, seconds <= 300,
              let ownership = input["ownership"] as? [String: String],
              let label = ownership["label"], let path = ownership["event_path"], input["allow_refresh"] as? Bool == true else {
            throw Blocked("invalid_scripting_grant")
        }
        for value in allowed {
            guard let parsed = URLComponents(string: value), let host = parsed.host,
                  !value.contains("\n"), !value.contains("\r"), parsed.user == nil, parsed.password == nil, parsed.fragment == nil,
                  parsed.scheme == "https" || (r["local_fixture"] as? Bool == true && parsed.scheme == "http" && ["127.0.0.1", "localhost", "::1"].contains(host)) else {
                throw Blocked("invalid_scripting_url")
            }
        }
        request = r; urls = allowed; deadline = Date().addingTimeInterval(Double(seconds))
        process = try Self.application()
        guard let identity = ScriptingProcessIdentity.read(process.processIdentifier) else { throw Blocked("safari_process_identity_unavailable") }
        processIdentity = identity; launchID = identity.launchID
        owner = try SessionOwnership(label: label + " · background Safari", eventPath: path, cancelPath: ownership["cancel_path"])
    }
    func check() throws {
        try owner.update("Relay background Safari · window " + String(windowID))
        guard Date() < deadline, calls < 20 else { throw Blocked("scripting_session_expired") }
        guard ScriptingProcessIdentity.read(processIdentity.pid) == processIdentity else { throw Blocked("safari_process_changed") }
    }
    func prefix(_ expected: String) -> String {
        "set ownedWindow to window id " + String(windowID) + "\n" +
        "if (count of tabs of ownedWindow) is not 1 then error \"owned tab changed\" number -2701\n" +
        "set ownedTab to current tab of ownedWindow\n" +
        "if (URL of ownedTab) is not " + Self.quote(expected) + " then error \"owned URL changed\" number -2702\n"
    }
    func waitForURL(_ destination: String, from source: String) async throws {
        // Observe the one acknowledged navigation; never repeat its setter.
        // Only its exact source may remain while loading. Any third URL is a
        // redirect or takeover, not authority to read a different document.
        for index in 0..<15 {
            try check()
            let result = try Self.script("set ownedWindow to window id " + String(windowID) + "\n" +
                "if (count of tabs of ownedWindow) is not 1 then error \"owned tab changed\" number -2701\n" +
                "return URL of current tab of ownedWindow", phase: "navigation_url_settle")
            guard let actual = result.stringValue else { throw Blocked("safari_navigation_url_unavailable") }
            if actual == destination { return }
            guard actual == source else { throw Blocked("safari_navigation_redirect_or_takeover") }
            if index < 14 { try await Task.sleep(for: .milliseconds(200)) }
        }
        throw Blocked("safari_navigation_destination_not_reached_no_replay")
    }
    func launch() async throws {
        try check()
        // Snapshot numeric IDs, not live index-based window references. Safari
        // can reorder its window collection while a new document opens.
        func ids(_ phase: String) throws -> Set<Int> {
            let result = try Self.script("return id of every window", phase: phase)
            var values = Set<Int>()
            for index in 0..<result.numberOfItems {
                guard let item = result.atIndex(index + 1), item.int32Value > 0,
                      values.insert(Int(item.int32Value)).inserted else {
                    throw Blocked("safari_window_identity_invalid")
                }
            }
            return values
        }
        let before = try ids("window_snapshot_before")
        try check()
        // Exactly one create dispatch. Never retry on error or missing identity.
        try Self.createBlankDocument()
        try check()
        let fresh = try ids("window_snapshot_after").subtracting(before)
        guard fresh.count == 1, let created = fresh.first else { throw Blocked("safari_window_identity_ambiguous") }
        windowID = created
        // Bind the sole new blank tab before loading the exact granted URL.
        // Keeping loading out of make-document avoids its ambiguous timeout.
        // No blank page can be returned as research evidence.
        _ = try Self.script(prefix("about:blank") + "set URL of ownedTab to " + Self.quote(request["expected_url"] as! String) + "\nreturn true", phase: "window_initial_navigate")
        try await waitForURL(request["expected_url"] as! String, from: "about:blank")
        request["target"] = ["pid": Int(process.processIdentifier), "launch_id": launchID, "window_id": windowID] as [String: Any]
    }
    func sample() throws -> String {
        try check()
        let expected = request["expected_url"] as! String
        if javascriptAvailable == nil {
            do {
                _ = try Self.script(prefix(expected) + "do JavaScript \"0\" in ownedTab", phase: "javascript_probe")
                javascriptAvailable = true
            } catch let error as Blocked {
                guard error.code == "safari_allow_javascript_from_apple_events_required" else { throw error }
                javascriptAvailable = false
            }
        }
        let data = try Self.script(prefix(expected) + """
        set pageText to text of ownedTab
        set pageHTML to source of ownedTab
        if (count of characters of pageText) > 20000 then set pageText to text 1 thru 20000 of pageText
        if (count of characters of pageHTML) > 500000 then set pageHTML to text 1 thru 500000 of pageHTML
        if (URL of ownedTab) is not \(Self.quote(expected)) then error "URL changed during read" number -2702
        return {pageText, pageHTML}
        """, phase: "document_read")
        try check()
        guard data.numberOfItems == 2, let text = data.atIndex(1)?.stringValue,
              let html = data.atIndex(2)?.stringValue, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw Blocked("safari_page_text_unavailable")
        }
        let lower = text.lowercased()
        if ["sign in to x", "verify you are human", "temporarily limited your login", "captcha"].contains(where: { lower.contains($0) }) {
            throw Blocked("login_or_challenge_requires_user")
        }
        // Links are evidence only, never an expanded navigation grant.
        let regex = try NSRegularExpression(pattern: "(?i)<a\\b[^>]*\\bhref\\s*=\\s*[\"']([^\"']+)[\"']")
        let range = NSRange(html.startIndex..<html.endIndex, in: html)
        var links: [String] = []
        for match in regex.matches(in: html, range: range).prefix(100) {
            guard let r = Range(match.range(at: 1), in: html) else { continue }
            let raw = String(html[r]).replacingOccurrences(of: "&amp;", with: "&")
            guard let url = URL(string: raw, relativeTo: URL(string: expected))?.absoluteURL,
                  url.scheme == "https" || (request["local_fixture"] as? Bool == true && url.scheme == "http"),
                  url.user == nil, url.password == nil, url.absoluteString.utf8.count <= 2000 else { continue }
            if !links.contains(url.absoluteString) { links.append(url.absoluteString) }
        }
        if javascriptAvailable == true {
            let js = "JSON.stringify(Array.from(document.links).slice(0,150).map(a=>a.href).filter(u=>u.startsWith('https://')||u.startsWith('http://')).map(u=>u.slice(0,2000)).slice(0,100))"
            let reply = try Self.script(prefix(expected) + "do JavaScript " + Self.quote(js) + " in ownedTab", phase: "link_read")
            guard let raw = reply.stringValue?.data(using: .utf8), raw.count <= 210000,
                  let dynamic = try JSONSerialization.jsonObject(with: raw) as? [String] else { throw Blocked("safari_link_snapshot_invalid") }
            links = dynamic
        }
        return text + (links.isEmpty ? "" : "\n\nLinks found in " + (javascriptAvailable == true ? "loaded DOM" : "HTML source; dynamic post links may be missing") + " (not independently visited):\n" + links.joined(separator: "\n"))
    }
    func observation(settling: Bool) async throws -> [String: Any] {
        var previous = ""
        for index in 0..<15 {
            do {
                let text = try sample()
                if text == previous {
                    let bytes = Data(text.utf8)
                    let limited = bytes.count > 23990 ? String(decoding: bytes.prefix(23990), as: UTF8.self) : text
                    return ["protocol": protocolID, "ok": true, "target": request["target"]!,
                            "url": request["expected_url"]!, "document_stable": true,
                            "captured_at": ISO8601DateFormatter().string(from: Date()), "text": limited,
                            "truncated": bytes.count > 18000,
                            "coverage": ["safari_apple_event_loaded_document_text", "html_links_not_visited",
                                         "bounded_text_and_html_may_omit_content", "no_claim_of_complete_timeline_or_thread"]]
                }
                previous = text
            } catch let error as Blocked {
                // Only empty/loading text can settle. A changed URL, missing
                // window, denied permission or uncertain Apple Event stops.
                guard settling, error.code == "safari_page_text_unavailable", index < 14 else { throw error }
            }
            try await Task.sleep(for: .milliseconds(300))
        }
        throw Blocked("safari_scripting_document_not_stable")
    }
    func step(_ input: [String: Any]) async throws -> [String: Any] {
        try check()
        guard let operation = input["operation"] as? String else { throw Blocked("missing_scripting_operation") }
        if operation == "launch" {
            guard windowID == 0 else { throw Blocked("scripting_launch_replay_blocked") }
            try await launch()
        } else {
            guard input["token"] as? String == token, !token.isEmpty,
                  let expected = input["observation_request"] as? [String: Any],
                  NSDictionary(dictionary: expected["target"] as? [String: Any] ?? [:]).isEqual(to: request["target"] as? [String: Any] ?? [:]),
                  ["observe", "navigate", "scroll"].contains(operation) else { throw Blocked("scripting_stale_token_or_target") }
            if operation == "navigate" {
                // Exact-URL navigation does not target page content. Validate
                // ownership, source URL and challenges, but a changing timer
                // must not prevent leaving the otherwise unchanged owned tab.
                _ = try sample()
            } else {
                let fresh = try await observation(settling: false)
                if operation == "scroll", fresh["text"] as? String != lastText {
                    return reply(fresh, operation: operation, refreshed: true)
                }
            }
            try check()
            if operation == "navigate" {
                guard let url = input["url"] as? String, urls.contains(url) else { throw Blocked("navigation_url_not_granted") }
                _ = try Self.script(prefix(request["expected_url"] as! String) + "set URL of ownedTab to " + Self.quote(url), phase: "navigate")
                try await waitForURL(url, from: request["expected_url"] as! String)
                request["expected_url"] = url
            } else if operation == "scroll" {
                guard let direction = input["direction"] as? String, ["up", "down"].contains(direction) else { throw Blocked("invalid_scroll_direction") }
                // Fixed JS only; the model cannot supply executable text.
                let js = "window.scrollBy(0, " + (direction == "up" ? "-" : "") + "Math.max(1,window.innerHeight-80)); window.scrollY"
                _ = try Self.script(prefix(request["expected_url"] as! String) + "do JavaScript " + Self.quote(js) + " in ownedTab", phase: "scroll")
            }
        }
        let result = try await observation(settling: operation == "launch" || operation == "navigate")
        return reply(result, operation: operation, refreshed: false)
    }
    func reply(_ observation: [String: Any], operation: String, refreshed: Bool) -> [String: Any] {
        calls += 1; token = UUID().uuidString; lastText = observation["text"] as? String ?? ""
        return ["observation": observation, "token": token, "refreshed": refreshed,
                "transport": "safari-scripting", "scroll_available": javascriptAvailable == true, "window_created": operation == "launch",
                "foreground_acquired": false, "action_executed": !refreshed && ["launch", "navigate", "scroll"].contains(operation)]
    }
}

@main
struct ComputerObserver {
    @MainActor static var scripting: SafariScriptingSession?
    @MainActor static var ownership: SessionOwnership?
    @MainActor static var allowRefresh = false
    @MainActor static var sessionRequest: [String: Any]?
    @MainActor static var boundWindow: AXUIElement?
    @MainActor static var boundArea: AXUIElement?
    @MainActor static var boundTab: AXUIElement?
    @MainActor static var boundContainer: AXUIElement?
    @MainActor static var snapshotWindow: AXUIElement?
    @MainActor static var snapshotArea: AXUIElement?
    @MainActor static var snapshotTab: AXUIElement?
    @MainActor static var token = ""
    @MainActor static var lastText = ""
    @MainActor static var allowedURLs: [String] = []
    @MainActor static var deadline = Date.distantPast
    @MainActor static var calls = 0

    @MainActor static func sessionStep(_ input: [String: Any]) async throws -> [String: Any] {
        guard input["protocol"] as? String == protocolID,
              let operation = input["operation"] as? String else { throw Blocked("invalid_session_request") }
        if operation == "launch", let r = input["observation_request"] as? [String: Any],
           r["target"] as? [String: String] == ["mode": "new-scripting-window"] {
            guard scripting == nil, sessionRequest == nil else { throw Blocked("session_already_bound") }
            scripting = try SafariScriptingSession(input); ownership = scripting?.owner
        }
        if let scripting { return try await scripting.step(input) }
        if operation == "bind" || operation == "launch" {
            guard sessionRequest == nil, let request = input["observation_request"] as? [String: Any],
                  let urls = input["allowed_urls"] as? [String], urls.count > 0, urls.count <= 10,
                  let initial = request["expected_url"] as? String, urls.contains(initial),
                  let seconds = input["max_seconds"] as? Int, seconds > 0, seconds <= 300 else {
                throw Blocked("invalid_session_grant")
            }
            for url in urls {
                guard let parsed = URLComponents(string: url), let host = parsed.host,
                      parsed.user == nil, parsed.password == nil, parsed.fragment == nil,
                      parsed.scheme == "https" || ((request["local_fixture"] as? Bool) == true &&
                      parsed.scheme == "http" && ["127.0.0.1", "localhost", "::1"].contains(host)) else {
                    throw Blocked("invalid_session_url")
                }
            }
            allowedURLs = urls; deadline = Date().addingTimeInterval(Double(seconds))
            sessionRequest = request
            allowRefresh = input["allow_refresh"] as? Bool == true
            if let owner = input["ownership"] as? [String: String],
               let label = owner["label"], let path = owner["event_path"] {
                ownership = try SessionOwnership(label: label, eventPath: path, cancelPath: owner["cancel_path"])
            } else if allowRefresh { throw Blocked("visible_ownership_required") }
        } else {
            guard sessionRequest != nil, input["token"] as? String == token,
                  Date() < deadline, calls < 20 else { throw Blocked("session_stale_or_expired") }
        }
        try ownership?.update("Relay: " + operation + " · Safari window " + String((sessionRequest?["target"] as? [String: Any])?["window_id"] as? Int ?? 0))
        if operation == "launch" {
            guard allowRefresh, let startup = sessionRequest else { throw Blocked("managed_launch_requires_ownership") }
            sessionRequest = try await launchWindow(startup)
        }
        calls += 1
        guard var request = sessionRequest else { throw Blocked("session_not_bound") }
        if operation != "bind" && operation != "launch" {
            // Fresh validation before effects, without producing an extra image.
            var check = request; check["capture"] = false
            var fresh = try await settledObservation(check)
            if operation != "observe", fresh["text"] as? String != lastText {
                guard allowRefresh else { throw Blocked("observation_changed_before_action") }
                // A positive no-effect receipt replaces the token. The model
                // sees new evidence and chooses anew; this action is not replayed.
                token = UUID().uuidString; lastText = fresh["text"] as? String ?? ""
                fresh["protocol"] = protocolID; fresh["ok"] = true
                try ownership?.update("Page updated · worker reconsidering; no action taken")
                return ["observation": fresh, "token": token, "refreshed": true, "action_executed": false]
            }
            try ownership?.update("Relay: " + operation)
            guard let window = snapshotWindow, let area = snapshotArea,
                  let container = parentElement(area) else { throw Blocked("session_binding_unavailable") }
            if operation == "navigate" {
                guard let destination = input["url"] as? String, allowedURLs.contains(destination) else {
                    throw Blocked("navigation_url_not_granted")
                }
                let field = try addressField(window)
                var settable: DarwinBoolean = false
                guard actionNames(field).contains(kAXConfirmAction as String),
                      AXUIElementIsAttributeSettable(field, kAXValueAttribute as CFString, &settable) == .success,
                      settable.boolValue else { throw Blocked("address_confirmation_unavailable") }
                // Element-targeted set/confirm only. No global Return, keyboard,
                // mouse click, clipboard or focused composer input is exposed.
                _ = try await handle(check)
                try ownership?.update("Relay: navigate")
                guard AXUIElementSetAttributeValue(field, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success else {
                    throw Blocked("address_focus_failed")
                }
                _ = try await handle(check)
                try ownership?.update("Relay: navigate")
                guard AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, destination as CFString) == .success else {
                    throw Blocked("address_value_not_set")
                }
                // Recheck the bound window/tab after the field edit and before submit.
                _ = try await handle(check)
                try ownership?.update("Relay: navigate")
                guard string(field, kAXValueAttribute) == destination,
                      AXUIElementPerformAction(field, kAXConfirmAction as CFString) == .success else {
                    throw Blocked("address_confirmation_failed")
                }
                request["expected_url"] = destination
            } else if operation == "scroll" {
                guard let direction = input["direction"] as? String, ["up", "down"].contains(direction) else {
                    throw Blocked("invalid_scroll_direction")
                }
                let action = direction == "down" ? "AXScrollDownByPage" : "AXScrollUpByPage"
                let target = actionNames(container).contains(action) ? container : area
                try ownership?.update("Relay: scroll")
                if actionNames(target).contains(action) {
                    guard AXUIElementPerformAction(target, action as CFString) == .success else {
                        throw Blocked("document_scroll_failed")
                    }
                } else {
                    // Safari exposes a normalized settable document scrollbar,
                    // with a full-document AXWebArea frame. Limit the requested
                    // offset to 90% of one viewport; never send PageDown/Space.
                    let bars = children(container).filter {
                        string($0, kAXRoleAttribute) == "AXScrollBar" &&
                        string($0, kAXOrientationAttribute) == "AXVerticalOrientation"
                    }
                    guard bars.count == 1, let viewport = frame(container), let document = frame(area),
                          let value = attribute(bars[0], kAXValueAttribute) as? NSNumber,
                          value.doubleValue.isFinite, (0...1).contains(value.doubleValue),
                          document.height.isFinite, document.height > viewport.height else {
                        throw Blocked("document_scroll_geometry_unavailable")
                    }
                    var settable: DarwinBoolean = false
                    guard AXUIElementIsAttributeSettable(bars[0], kAXValueAttribute as CFString, &settable) == .success,
                          settable.boolValue else { throw Blocked("document_scrollbar_not_settable") }
                    let delta = 0.9 * viewport.height / (document.height - viewport.height)
                    let next = min(1, max(0, value.doubleValue + (direction == "down" ? delta : -delta)))
                    guard AXUIElementSetAttributeValue(bars[0], kAXValueAttribute as CFString, NSNumber(value: next)) == .success else {
                        throw Blocked("document_scroll_failed")
                    }
                }
                try await Task.sleep(for: .milliseconds(100))
            } else if operation != "observe" { throw Blocked("unsupported_session_operation") }
        }
        // This wait observes load/scroll settling only; the action is never repeated.
        var observation: [String: Any]?
        for _ in 0..<20 {
            do {
                observation = try await settledObservation(request)
                break
            } catch let error as Blocked {
                let settling = ["selected_document_url_changed_or_unavailable", "visible_text_unavailable",
                                "document_changed_during_observation", "document_geometry_changed_during_observation",
                                "active_web_document_not_unique"]
                guard (operation == "navigate" || operation == "scroll" || operation == "launch"), settling.contains(error.code), Date() < deadline else { throw error }
                // An unexpected nonempty URL is an out-of-scope redirect, not a retry target.
                if operation == "navigate" || operation == "launch", let window = boundWindow, let rect = frame(window),
                   let area = try? webArea(window, bounds: rect), let actual = documentURL(area),
                   actual != request["expected_url"] as? String,
                   actual != sessionRequest?["expected_url"] as? String, actual != "about:blank", !actual.isEmpty {
                    throw Blocked("unexpected_navigation_destination")
                }
                try await Task.sleep(for: .milliseconds(100))
            }
        }
        guard var observation else { throw Blocked("navigation_or_scroll_observation_not_ready") }
        guard let window = snapshotWindow, let area = snapshotArea,
              let container = parentElement(area), string(container, kAXRoleAttribute) == "AXScrollArea" else {
            throw Blocked("stable_document_container_required")
        }
        boundWindow = window; boundArea = area; boundContainer = container; boundTab = snapshotTab
        sessionRequest = request; token = UUID().uuidString
        lastText = observation["text"] as? String ?? ""
        observation["protocol"] = protocolID; observation["ok"] = true
        try ownership?.update("Worker reviewing page · Safari remains owned")
        return ["observation": observation, "token": token, "refreshed": false,
                "window_created": operation == "launch", "foreground_acquired": operation == "launch",
                "action_executed": operation == "launch" || operation == "navigate" || operation == "scroll"]
    }

    // Startup is a single journaled effect. No retry, existing-window navigation,
    // generic keyboard synthesis or focus reacquisition is exposed to the model.
    @MainActor static func launchWindow(_ request: [String: Any]) async throws -> [String: Any] {
        guard request["target"] as? [String: String] == ["mode": "new-window"],
              request["capture"] as? Bool == false,
              let destination = request["expected_url"] as? String,
              allowedURLs.contains(destination) else { throw Blocked("invalid_launch_scope") }
        try requireAccess()
        try ownership?.update("Opening dedicated Safari window")
        let application: NSRunningApplication
        let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.Safari")
        if running.count == 1 { application = running[0] }
        else if running.isEmpty {
            guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Safari") else {
                throw Blocked("safari_not_installed")
            }
            let configuration = NSWorkspace.OpenConfiguration(); configuration.activates = false
            application = try await NSWorkspace.shared.openApplication(at: url, configuration: configuration)
        } else { throw Blocked("safari_process_not_unique") }
        try ownership?.update("Bringing Safari forward for this task")
        try requireAccess()
        guard application.activate(options: [.activateIgnoringOtherApps]) else { throw Blocked("safari_activation_failed") }
        let startupDeadline = min(deadline, Date().addingTimeInterval(12))
        while NSWorkspace.shared.frontmostApplication?.processIdentifier != application.processIdentifier {
            try ownership?.update("Waiting for Safari foreground")
            guard Date() < startupDeadline else { throw Blocked("safari_foreground_unavailable") }
            try await Task.sleep(for: .milliseconds(100))
        }
        let appAX = AXUIElementCreateApplication(application.processIdentifier)
        func check(_ window: AXUIElement? = nil) throws {
            try requireAccess(); try ownership?.update("Starting dedicated Safari window")
            guard Date() < startupDeadline,
                  NSWorkspace.shared.frontmostApplication?.processIdentifier == application.processIdentifier else {
                throw Blocked("safari_startup_focus_lost")
            }
            if let window {
                guard let focused = attribute(appAX, kAXFocusedWindowAttribute), CFEqual(focused, window) else {
                    throw Blocked("safari_startup_window_changed")
                }
            }
        }
        func menu(_ identifier: String) throws -> AXUIElement {
            guard let bar = attribute(appAX, kAXMenuBarAttribute), CFGetTypeID(bar) == AXUIElementGetTypeID() else {
                throw Blocked("safari_menu_unavailable")
            }
            var queue = [bar as! AXUIElement], found: [AXUIElement] = [], count = 0
            while !queue.isEmpty {
                let item = queue.removeFirst(); count += 1
                guard count < 2000 else { throw Blocked("safari_menu_exceeds_limit") }
                if string(item, kAXIdentifierAttribute) == identifier { found.append(item) }
                queue += children(item)
            }
            guard found.count == 1, (attribute(found[0], kAXEnabledAttribute) as? Bool) == true,
                  actionNames(found[0]).contains(kAXPressAction as String) else { throw Blocked("safari_window_menu_unavailable") }
            return found[0]
        }
        // Snapshot every existing AX/SC window before the single New Window action.
        let oldAX = (attribute(appAX, kAXWindowsAttribute) as? [AXUIElement]) ?? []
        let before = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
        let oldIDs = Set(before.windows.map { $0.windowID })
        let create = try menu("NewWindow?isDefaultProfile=true")
        try check()
        guard AXUIElementPerformAction(create, kAXPressAction as CFString) == .success else { throw Blocked("safari_new_window_failed") }
        var window: AXUIElement?
        while window == nil {
            try check()
            let all = (attribute(appAX, kAXWindowsAttribute) as? [AXUIElement]) ?? []
            let fresh = all.filter { item in !oldAX.contains { CFEqual(item, $0) } }
            guard fresh.count <= 1 else { throw Blocked("safari_new_window_ambiguous") }
            if let first = fresh.first { window = first }
            else { try await Task.sleep(for: .milliseconds(100)) }
        }
        guard let window else { throw Blocked("safari_new_window_missing") }
        try check(window)
        boundWindow = window
        if (try? selectedTab(window)) == nil {
            let show = try menu("AlwaysShowTabBar")
            try check(window)
            guard AXUIElementPerformAction(show, kAXPressAction as CFString) == .success else { throw Blocked("safari_tab_bar_unavailable") }
            try await Task.sleep(for: .milliseconds(100))
        }
        boundTab = try selectedTab(window)
        let field = try addressField(window)
        try check(window)
        guard AXUIElementSetAttributeValue(field, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success else {
            throw Blocked("address_focus_failed")
        }
        try check(window)
        guard AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, destination as CFString) == .success else {
            throw Blocked("address_value_not_set")
        }
        try check(window)
        guard string(field, kAXValueAttribute) == destination,
              AXUIElementPerformAction(field, kAXConfirmAction as CFString) == .success else { throw Blocked("address_confirmation_failed") }
        // Only the newly created SC window may supply the persistent binding.
        var selected: SCWindow?
        while selected == nil {
            try check(window)
            let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
            let fresh = content.windows.filter { !oldIDs.contains($0.windowID) &&
                $0.owningApplication?.processID == application.processIdentifier && $0.windowLayer == 0 }
            guard fresh.count <= 1 else { throw Blocked("safari_new_window_ambiguous") }
            if let first = fresh.first, let rect = frame(window), sameFrame(first.frame, rect) { selected = first }
            else { try await Task.sleep(for: .milliseconds(100)) }
        }
        guard let selected, let launched = application.launchDate else { throw Blocked("safari_launch_identity_missing") }
        var result = request
        result["target"] = ["pid": Int(application.processIdentifier),
                            "launch_id": String(format: "%.6f", launched.timeIntervalSince1970),
                            "window_id": Int(selected.windowID)] as [String: Any]
        return result
    }

    @MainActor static func settledObservation(_ request: [String: Any]) async throws -> [String: Any] {
        for attempt in 0..<5 {
            do { return try await handle(request) }
            catch let error as Blocked {
                guard attempt < 4, ["document_changed_during_observation", "document_geometry_changed_during_observation"].contains(error.code) else { throw error }
                guard ownership?.halted != true else { throw Blocked("session_ownership_released") }
                try await Task.sleep(for: .milliseconds(100))
            }
        }
        throw Blocked("dynamic_document_not_stable")
    }

    // Read stdin off the main thread so AppKit buttons keep working while the
    // provider is thinking and while native observation awaits settling.
    static func nextLine() async throws -> Data? {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global().async {
                do {
                    var raw = Data()
                    while raw.count <= 24000 {
                        let byte = try FileHandle.standardInput.read(upToCount: 1) ?? Data()
                        if byte.isEmpty { continuation.resume(returning: nil); return }
                        if byte.first == 10 { continuation.resume(returning: raw); return }
                        raw.append(byte)
                    }
                    throw Blocked("invalid_session_request")
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    @MainActor static func handle(_ request: [String: Any]) async throws -> [String: Any] {
        guard request["protocol"] as? String == protocolID else { throw Blocked("protocol_mismatch") }
        let operation = request["operation"] as? String ?? ""
        if operation == "status" { return status() }
        if operation == "scripting-status" { return try SafariScriptingSession.status() }
        if operation == "request-permissions" {
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(options)
            _ = CGRequestScreenCaptureAccess()
            return status().merging(["permission_prompted": true]) { _, new in new }
        }
        guard ["windows", "observe"].contains(operation) else { throw Blocked("unsupported_operation") }
        try requireAccess()
        // One-shot CLI launches do not run NSApplicationMain. Initialize AppKit's
        // display connection before ScreenCaptureKit constructs a window filter.
        // Accessory policy does not activate the helper or create a Dock window.
        NSApplication.shared.setActivationPolicy(.accessory)
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        let safari = content.windows.filter { $0.owningApplication?.bundleIdentifier == "com.apple.Safari" && $0.windowLayer == 0 }
        func identity(_ window: SCWindow) throws -> [String: Any] {
            guard let pid = window.owningApplication?.processID,
                  let app = NSRunningApplication(processIdentifier: pid), let launch = app.launchDate else {
                throw Blocked("process_identity_unavailable")
            }
            return ["pid": Int(pid), "launch_id": String(format: "%.6f", launch.timeIntervalSince1970),
                    "window_id": Int(window.windowID)]
        }
        if operation == "windows" {
            // Identify the focused target without returning titles, URLs or tab contents.
            let foreground = NSWorkspace.shared.frontmostApplication?.processIdentifier
            let entries = try safari.map { window -> [String: Any] in
                var entry = try identity(window)
                entry["frame"] = [window.frame.minX, window.frame.minY, window.frame.width, window.frame.height]
                let pid = window.owningApplication!.processID
                let app = AXUIElementCreateApplication(pid)
                AXUIElementSetMessagingTimeout(app, 2)
                let focused = attribute(app, kAXFocusedWindowAttribute)
                var matchesFocus = false
                var focusReason = foreground == pid ? "focused_window_unavailable" : "safari_not_foreground"
                if foreground == pid, let focused, CFGetTypeID(focused) == AXUIElementGetTypeID(),
                   let rect = frame(focused as! AXUIElement) {
                    var matches = safari.filter {
                        $0.owningApplication?.processID == pid && sameFrame($0.frame, rect)
                    }
                    if matches.count > 1, let title = string(focused as! AXUIElement, kAXTitleAttribute), !title.isEmpty {
                        matches = matches.filter { $0.title == title }
                    }
                    entry["focused_frame"] = [rect.minX, rect.minY, rect.width, rect.height]
                    entry["focused_frame_matches"] = matches.count
                    matchesFocus = matches.count == 1 && matches[0].windowID == window.windowID
                    focusReason = matches.count != 1 ? "focused_window_bounds_ambiguous" : (matchesFocus ? "selected" : "other_window")
                }
                entry["focused"] = matchesFocus
                entry["focus_reason"] = focusReason
                return entry
            }
            return ["windows": entries, "application": "com.apple.Safari"]
        }
        guard let selected = request["target"] as? [String: Any],
              let pid = selected["pid"] as? Int, let number = selected["window_id"] as? Int,
              let launch = selected["launch_id"] as? String, let expectedURL = request["expected_url"] as? String,
              let parsed = URLComponents(string: expectedURL), let host = parsed.host,
              parsed.user == nil, parsed.password == nil, parsed.fragment == nil,
              parsed.scheme == "https" || ((request["local_fixture"] as? Bool) == true && parsed.scheme == "http" && ["127.0.0.1", "localhost", "::1"].contains(host)),
              let selectedWindow = safari.first(where: { Int($0.windowID) == number && Int($0.owningApplication!.processID) == pid }),
              try identity(selectedWindow)["launch_id"] as? String == launch else {
            throw Blocked("target_or_url_invalid")
        }
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid_t(pid) else {
            throw Blocked("selected_safari_must_be_foreground")
        }
        let appAX = AXUIElementCreateApplication(pid_t(pid))
        AXUIElementSetMessagingTimeout(appAX, 2)
        guard let windows = attribute(appAX, kAXWindowsAttribute) as? [AXUIElement] else {
            throw Blocked("accessible_windows_unavailable")
        }
        var matching = windows.filter { frame($0).map { sameFrame($0, selectedWindow.frame) } ?? false }
        if let boundWindow {
            // An existing binding survives a navigation title update only by
            // retaining the exact AX window object, never by choosing a title.
            matching = matching.filter { CFEqual($0, boundWindow) }
        } else if matching.count > 1, let title = selectedWindow.title, !title.isEmpty {
            matching = matching.filter { string($0, kAXTitleAttribute) == title }
        }
        guard matching.count == 1, let window = matching.first,
              let focused = attribute(appAX, kAXFocusedWindowAttribute), CFEqual(focused, window) else {
            throw Blocked("selected_window_changed_or_ambiguous")
        }
        let area = try webArea(window, bounds: selectedWindow.frame)
        let tab = sessionRequest != nil ? try selectedTab(window) : nil
        if let boundWindow, let boundTab {
            guard CFEqual(boundWindow, window), let tab, CFEqual(boundTab, tab) else {
                throw Blocked("bound_tab_or_document_changed")
            }
        }
        guard documentURL(area) == expectedURL else { throw Blocked("selected_document_url_changed_or_unavailable") }
        guard let areaFrame = frame(area) else { throw Blocked("document_bounds_unavailable") }
        let viewport = areaFrame.intersection(selectedWindow.frame)
        let before = readDocument(area, bounds: viewport)
        guard !before.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw Blocked("visible_text_unavailable") }
        // Conservative challenge detection is a blocker, not a universal login detector.
        let lower = before.text.lowercased()
        if ["sign in to x", "verify you are human", "temporarily limited your login", "captcha"].contains(where: { lower.contains($0) }) {
            throw Blocked("login_or_challenge_requires_user")
        }
        var result: [String: Any] = ["target": selected, "url": expectedURL, "text": before.text,
            "truncated": before.truncated, "captured_at": ISO8601DateFormatter().string(from: Date()),
            "coverage": ["visible_accessibility_static_text_only", "editable_controls_and_frames_excluded",
                         "no_claim_of_complete_page_or_thread", "no_independent_fact_review"]]
        if (request["capture"] as? Bool) == true {
            guard before.captureAllowed, !before.truncated else { throw Blocked("incomplete_or_editable_document_capture_blocked") }
            let filter = SCContentFilter(desktopIndependentWindow: selectedWindow)
            let config = SCStreamConfiguration()
            config.width = Int(selectedWindow.frame.width.rounded(.up))
            config.height = Int(selectedWindow.frame.height.rounded(.up))
            guard config.width > 0, config.height > 0, config.width <= 4096, config.height <= 4096,
                  config.width * config.height <= 8000000 else { throw Blocked("window_image_exceeds_limits") }
            config.showsCursor = false
            config.ignoreShadowsSingleWindow = true
            if #available(macOS 14.2, *) { config.includeChildWindows = false }
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
            let bytes = NSMutableData()
            guard let dest = CGImageDestinationCreateWithData(bytes, UTType.png.identifier as CFString, 1, nil) else { throw Blocked("png_encoder_unavailable") }
            CGImageDestinationAddImage(dest, image, nil)
            guard CGImageDestinationFinalize(dest), bytes.length <= 10000000 else { throw Blocked("png_capture_failed_or_oversized") }
            result["png_base64"] = (bytes as Data).base64EncodedString()
        }
        // No pixel/text release until target, AX document identity and text are rechecked.
        try requireAccess()
        let afterContent = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        guard let afterWindow = afterContent.windows.first(where: { $0.windowID == selectedWindow.windowID }),
              afterWindow.owningApplication?.bundleIdentifier == "com.apple.Safari",
              afterWindow.owningApplication?.processID == pid_t(pid),
              try identity(afterWindow)["launch_id"] as? String == launch,
              sameFrame(afterWindow.frame, selectedWindow.frame),
              NSWorkspace.shared.frontmostApplication?.processIdentifier == pid_t(pid),
              let afterFocus = attribute(appAX, kAXFocusedWindowAttribute), CFEqual(afterFocus, window) else {
            throw Blocked("target_changed_during_observation")
        }
        if let tab { guard CFEqual(try selectedTab(window), tab) else { throw Blocked("tab_changed_during_observation") } }
        guard CFEqual(try webArea(window, bounds: selectedWindow.frame), area),
              documentURL(area) == expectedURL else {
            throw Blocked("selected_document_url_changed_or_unavailable")
        }
        // Virtualized timelines can resize/move their document during a page
        // scroll. Discard this observation and let the existing bounded settling
        // loop re-observe; never repeat the scroll or relax window/tab identity.
        guard let afterFrame = frame(area), sameFrame(afterFrame, areaFrame) else {
            throw Blocked("document_geometry_changed_during_observation")
        }
        let after = readDocument(area, bounds: viewport)
        guard before.text == after.text, before.truncated == after.truncated,
              (request["capture"] as? Bool) != true || after.captureAllowed else { throw Blocked("document_changed_during_observation") }
        result["document_stable"] = true
        snapshotWindow = window; snapshotArea = area; snapshotTab = tab
        return result
    }

    @MainActor static func sessionLoop() async {
        while true {
            do {
                guard let raw = try await nextLine() else { return }
                guard let input = try JSONSerialization.jsonObject(with: raw) as? [String: Any] else { throw Blocked("invalid_session_request") }
                var result = try await sessionStep(input)
                result["protocol"] = protocolID; result["ok"] = true
                var bytes = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
                bytes.append(10); FileHandle.standardOutput.write(bytes)
            } catch {
                let code = (error as? Blocked)?.code ?? "native_session_failed"
                let result: [String: Any] = ["protocol": protocolID, "ok": false, "error": code]
                if var bytes = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]) {
                    bytes.append(10); FileHandle.standardOutput.write(bytes)
                }
                return
            }
        }
    }

    @MainActor static func main() async {
        if CommandLine.arguments.dropFirst() == ["--session"] {
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            Task { await sessionLoop(); ownership?.panel.close(); app.terminate(nil) }
            app.run()
            return
        }
        var result: [String: Any]
        do {
            var raw = Data()
            while raw.count <= 24000 {
                let chunk = try FileHandle.standardInput.read(upToCount: 24001 - raw.count) ?? Data()
                if chunk.isEmpty { break }
                raw.append(chunk)
            }
            guard raw.count <= 24000, let request = try JSONSerialization.jsonObject(with: raw) as? [String: Any] else { throw Blocked("invalid_request") }
            result = try await handle(request)
            result["ok"] = true
        } catch let error as Blocked {
            result = ["ok": false, "error": error.code]
        } catch {
            // Native diagnostic descriptions can contain page data; return only a type.
            result = ["ok": false, "error": "native_observation_failed"]
        }
        result["protocol"] = protocolID
        if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data)
        }
    }
}
