import AppKit
import Foundation
import ServiceManagement
import Darwin

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let server = ServerProcess()
    private var stopping = false
    private var readyOutput = ""
    private var openingLogs = false
    private var logsURL: URL { Self.applicationSupportURL.appendingPathComponent("logs/ktvibes.log") }
    private var currentVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0"
    private var releaseURL = URL(string: "https://github.com/JeffShih-wiwynn/KTVibes/releases/latest")!
    private var updateVersion: String?
    private var versionItem: NSMenuItem!
    private var updateTimer: Timer?
    private var loginItem: NSMenuItem!
    private var network = NetworkPreferences.load()
    private var networkWindow: NetworkWindow?
    private var desktopToken = UUID().uuidString + UUID().uuidString
    private var instanceID = UUID().uuidString
    private var changingNetwork = false
    private var activePort: Int?
    private var portConflict = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = Self.makeStatusImage()
        statusItem.button?.toolTip = "KTVibes"
        let menu = NSMenu()
        versionItem = NSMenuItem(title: "", action: #selector(openRelease), keyEquivalent: "")
        versionItem.target = self
        menu.addItem(versionItem)
        menu.addItem(.separator())
        menu.addItem(withTitle: "Open Player", action: #selector(openPlayer), keyEquivalent: "")
        menu.addItem(withTitle: "Show Logs", action: #selector(showLogs), keyEquivalent: "")
        menu.addItem(withTitle: "Network Settings…", action: #selector(showNetworkSettings), keyEquivalent: "")
        menu.addItem(.separator())
        loginItem = NSMenuItem(title: "Launch at Login", action: #selector(toggleLaunchAtLogin), keyEquivalent: "")
        menu.addItem(loginItem)
        refreshLoginItemState()
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit", action: #selector(quit), keyEquivalent: "q")
        menu.items.forEach { $0.target = self }
        statusItem.menu = menu
        renderVersionItem()
        startKTVibes()
        updateTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in self?.refreshReleaseInfo() }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !stopping else { return .terminateCancel }
        setStopping(true)
        server.stop { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }

    private func startKTVibes() {
        guard !stopping else { return }
        guard let resources = Bundle.main.resourceURL, let executable = Bundle.main.executableURL else { return }
        let script = resources.appendingPathComponent("setup-and-run.sh")
        var environment = ProcessInfo.processInfo.environment.merging([
            "KTVIBES_APP_SUPPORT": Self.applicationSupportURL.path,
            "KTVIBES_APP_RESOURCES": resources.path
        ]) { _, new in new }
        environment["KTVIBES_PORT"] = String(network.port)
        environment["KTVIBES_AUTO_PORT"] = "1"
        environment["KTVIBES_PORT_FILE"] = Self.applicationSupportURL.appendingPathComponent("active-port").path
        environment["KTVIBES_ADVERTISE_IP"] = network.ip
        desktopToken = UUID().uuidString + UUID().uuidString
        environment["KTVIBES_DESKTOP_TOKEN"] = desktopToken
        environment["KTVIBES_EXTERNAL_ENABLED"] = (network.external_url ?? "").isEmpty ? "0" : "1"
        environment["KTVIBES_REMOTE_URL"] = network.external_url ?? ""
        environment["KTVIBES_CREDENTIAL_TYPE"] = network.credential_type ?? "password"
        environment["KTVIBES_PASSWORD_HASH"] = network.password_hash ?? ""
        networkWindow?.desktopToken = desktopToken
        instanceID = UUID().uuidString
        activePort = nil
        portConflict = false
        try? FileManager.default.removeItem(at: Self.applicationSupportURL.appendingPathComponent("active-port"))
        environment["KTVIBES_INSTANCE_ID"] = instanceID
        server.onOutput = { [weak self] text in
            guard let self else { return }
            self.readyOutput += text
            for line in text.components(separatedBy: .newlines) {
                if line.hasPrefix("KTVIBES_ACTIVE_PORT="), let port = Int(line.dropFirst("KTVIBES_ACTIVE_PORT=".count)) { self.activePort = port }
                if line.contains("KTVIBES_PORT_CONFLICT") { self.portConflict = true; self.renderVersionItem() }
            }
            if self.readyOutput.contains("KTVIBES_SERVER_READY") {
                self.readyOutput = ""
                // The menu bar app starts the server in the background. Users open the player explicitly.
            }
            self.readyOutput = String(self.readyOutput.suffix(64))
        }
        server.onExit = { [weak self] in
            self?.statusItem.button?.image = Self.makeStatusImage(stopped: true)
            self?.renderVersionItem()
        }
        do { try server.start(executable: executable, script: script, environment: environment, logURL: logsURL) }
        catch { NSLog("Could not start KTVibes: %@", error.localizedDescription) }
    }

    @objc private func openPlayer() {
        readActivePort()
        NSWorkspace.shared.open(URL(string: "http://localhost:\(activePort ?? network.port)")!)
    }

    private func readActivePort() {
        if let value = try? String(contentsOf: Self.applicationSupportURL.appendingPathComponent("active-port"), encoding: .ascii), let port = Int(value.trimmingCharacters(in: .whitespacesAndNewlines)) { activePort = port }
    }

    @objc private func showNetworkSettings() {
        readActivePort()
        if networkWindow == nil {
            networkWindow = NetworkWindow()
            networkWindow?.apply = { [weak self] preferences in self?.applyNetwork(preferences) }
        }
        networkWindow?.desktopToken = desktopToken
        networkWindow?.present(network, activePort: activePort, conflict: portConflict)
    }

    private func applyNetwork(_ next: NetworkPreferences) {
        guard !changingNetwork, next != network || portConflict else { return }
        let previous = network
        changingNetwork = true
        networkWindow?.busy(true, message: "Restarting…")
        server.stop { [weak self] in
            guard let self else { return }
            self.network = next
            self.startKTVibes()
            self.waitForNetwork(attempts: 150) { success in
                if success {
                    do {
                        try next.save()
                        self.changingNetwork = false
                        self.statusItem.button?.image = Self.makeStatusImage()
                        self.networkWindow?.busy(false, message: "Available")
                        self.networkWindow?.present(next, activePort: self.activePort, conflict: false)
                        self.openPlayer()
                    } catch { self.restoreNetwork(previous, reason: "Could not save settings: \(error.localizedDescription)") }
                } else { self.restoreNetwork(previous, reason: "The new server could not start. The port may be in use. Restoring previous settings…") }
            }
        }
    }

    private func restoreNetwork(_ previous: NetworkPreferences, reason: String) {
        networkWindow?.busy(true, message: reason)
        server.stop { [weak self] in
            guard let self else { return }
            self.network = previous
            self.startKTVibes()
            self.waitForNetwork(attempts: 150) { success in
                self.changingNetwork = false
                if success { self.statusItem.button?.image = Self.makeStatusImage() }
                self.networkWindow?.busy(false, message: success ? "Previous settings restored. Check the port and try again." : "Server unavailable. Open Show Logs for details.")
            }
        }
    }

    private func waitForNetwork(attempts: Int, completion: @escaping (Bool) -> Void) {
        guard !stopping, attempts > 0 else { completion(false); return }
        readActivePort()
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(activePort ?? network.port)/api/config")!, timeoutInterval: 1)
        request.setValue("Bearer " + desktopToken, forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                let config = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                if config?["instance_id"] as? String == self.instanceID { completion(true) }
                else { DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.waitForNetwork(attempts: attempts - 1, completion: completion) } }
            }
        }.resume()
    }

    @objc private func openRelease() {
        if portConflict { showNetworkSettings() } else { NSWorkspace.shared.open(releaseURL) }
    }

    @objc private func toggleLaunchAtLogin() {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled {
                try service.unregister()
            } else {
                try service.register()
            }
        } catch {
            SMAppService.openSystemSettingsLoginItems()
        }
        refreshLoginItemState()
    }

    private func refreshLoginItemState() {
        loginItem?.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    private func refreshReleaseInfo() {
        guard !stopping else { return }
        readActivePort()
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(activePort ?? network.port)/api/config")!, timeoutInterval: 3)
        request.setValue("Bearer " + desktopToken, forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
        guard let data, let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let self else { return }
            DispatchQueue.main.async {
                guard payload["instance_id"] as? String == self.instanceID else { return }
                if let version = payload["version"] as? String { self.currentVersion = version }
                if let update = payload["update"] as? [String: String],
                   let version = update["version"], let url = update["url"], let release = URL(string: url) {
                    self.updateVersion = version
                    self.releaseURL = release
                } else {
                    self.updateVersion = nil
                    self.releaseURL = URL(string: "https://github.com/JeffShih-wiwynn/KTVibes/releases/latest")!
                }
                self.renderVersionItem()
                if payload["update_check_complete"] as? Bool == true {
                    self.updateTimer?.invalidate()
                    self.updateTimer = nil
                }
            }
        }.resume()
    }

    private func renderVersionItem() {
        if portConflict { versionItem.title = "Port conflict"; versionItem.image = nil; return }
        let latest = updateVersion?.replacingOccurrences(of: "^v", with: "", options: .regularExpression)
        versionItem.title = latest.map { "Version \(currentVersion) → \($0)    ↗" } ?? "Version \(currentVersion)    ↗"
        versionItem.image = updateVersion == nil ? nil : NSImage(systemSymbolName: "arrow.down.to.line", accessibilityDescription: "Update available")
        versionItem.image?.isTemplate = true
    }

    @objc private func showLogs() {
        guard !openingLogs else { return }
        openingLogs = true
        let shellCommand = "tail -n 200 -F '\(logsURL.path.replacingOccurrences(of: "'", with: "'\\''"))'"
        let escaped = shellCommand.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let appleScript = """
        tell application "Terminal"
            activate
            set targetTab to missing value
            repeat with candidateWindow in windows
                repeat with candidateTab in tabs of candidateWindow
                    if custom title of candidateTab is "KTVibes Logs" then set targetTab to candidateTab
                end repeat
            end repeat
            if targetTab is missing value then
                set targetTab to do script "\(escaped)"
                set custom title of targetTab to "KTVibes Logs"
            else
                set index of (window of targetTab) to 1
            end if
        end tell
        """
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        task.arguments = ["-e", appleScript]
        let errorPipe = Pipe()
        task.standardError = errorPipe
        task.terminationHandler = { [weak self] finished in
            let data = errorPipe.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                self?.openingLogs = false
                if finished.terminationStatus != 0 { self?.showLogError(String(decoding: data, as: UTF8.self)) }
            }
        }
        do { try task.run() }
        catch { openingLogs = false; showLogError(error.localizedDescription) }
    }

    @objc private func quit() { NSApp.terminate(nil) }

    private func setStopping(_ value: Bool) {
        stopping = value
        statusItem.menu?.autoenablesItems = false
        statusItem.menu?.items.forEach { $0.isEnabled = !value }
    }

    private func showLogError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Could not show KTVibes logs"
        alert.informativeText = "Check that Terminal is available, then try again.\n\(message)"
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    private static var applicationSupportURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("KTVibes", isDirectory: true)
    }

    private static func makeStatusImage(stopped: Bool = false) -> NSImage {
        let size = NSSize(width: 24, height: 20)
        let image = NSImage(size: size)
        image.lockFocus()
        let font = NSFont.systemFont(ofSize: 15, weight: .semibold)
        let text = NSAttributedString(string: "KT", attributes: [
            .font: font,
            .kern: -0.7,
            .foregroundColor: NSColor.black
        ])
        let bounds = text.boundingRect(
            with: NSSize(width: size.width, height: size.height),
            options: [.usesLineFragmentOrigin, .usesFontLeading]
        )
        let origin = NSPoint(
            x: (size.width - bounds.width) / 2 - bounds.minX,
            y: (size.height - bounds.height) / 2 - bounds.minY
        )
        text.draw(at: origin)
        if stopped {
            let slash = NSBezierPath()
            slash.lineCapStyle = .round
            slash.move(to: NSPoint(x: 5, y: 3))
            slash.line(to: NSPoint(x: 19, y: 17))
            // A transparent gap keeps the slash distinct in both menu bar appearances.
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current?.compositingOperation = .clear
            slash.lineWidth = 4
            slash.stroke()
            NSGraphicsContext.restoreGraphicsState()
            NSColor.black.setStroke()
            slash.lineWidth = 1.5
            slash.stroke()
        }
        image.unlockFocus()
        image.isTemplate = true
        return image
    }
}

@main
enum KTVibesLauncher {
    static func main() {
        runServerHelperIfRequested()
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
