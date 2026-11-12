import Cocoa
import Foundation

struct NetworkPreferences: Codable, Equatable {
    var ip: String = ""
    var port: Int = 8765
    static var file: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("KTVibes/network.json")
    }
    static func load() -> Self {
        if let data = try? Data(contentsOf: file), let value = try? JSONDecoder().decode(Self.self, from: data), (1...65535).contains(value.port) { return value }
        return Self(ip: ProcessInfo.processInfo.environment["KTVIBES_ADVERTISE_IP"] ?? "", port: Int(ProcessInfo.processInfo.environment["KTVIBES_PORT"] ?? "8765").flatMap { (1...65535).contains($0) ? $0 : nil } ?? 8765)
    }
    func save() throws {
        try FileManager.default.createDirectory(at: Self.file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONEncoder().encode(self).write(to: Self.file, options: .atomic)
    }
}

final class NetworkWindow: NSObject, NSWindowDelegate {
    var apply: ((NetworkPreferences) -> Void)?
    private let window = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 480, height: 88), styleMask: [.titled, .closable], backing: .buffered, defer: false)
    private let status = NSTextField(wrappingLabelWithString: "Connecting…")
    private let address = NSTextField(labelWithString: "")
    private let networks = NSPopUpButton()
    private let port = NSTextField(string: "8765")
    private let portBackground = NSView()
    private let advanced = NSStackView()
    private let disclosure = NSButton(checkboxWithTitle: "Advanced settings", target: nil, action: nil)
    private let buttons = NSStackView()
    private let hint = NSTextField(labelWithString: "Applying changes will restart the server.")
    private var displayedPort = 8765
    private var ips = [""]
    private var timer: Timer?
    private var current = NetworkPreferences()
    private var saving = false
    private let applyButton = NSButton(title: "Apply", target: nil, action: nil)
    private let resetButton = NSButton(title: "Reset", target: nil, action: nil)

    override init() {
        super.init()
        window.title = "Network Settings"; window.delegate = self; window.isReleasedWhenClosed = false
        address.isSelectable = true
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        let copy = NSButton(title: "", target: self, action: #selector(copyAddress))
        copy.image = NSImage(systemSymbolName: "doc.on.doc", accessibilityDescription: "Copy address")
        copy.imagePosition = .imageOnly
        copy.isBordered = false
        copy.toolTip = "Copy address"
        copy.setAccessibilityLabel("Copy address")
        copy.widthAnchor.constraint(equalToConstant: 28).isActive = true
        let addressLabel = NSTextField(labelWithString: "Remote address")
        addressLabel.widthAnchor.constraint(equalToConstant: 105).isActive = true
        address.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let urlRow = NSStackView(views: [addressLabel, address, copy]); urlRow.spacing = 10
        urlRow.widthAnchor.constraint(equalToConstant: 440).isActive = true
        disclosure.target = self; disclosure.action = #selector(toggleAdvanced(_:))
        networks.widthAnchor.constraint(equalToConstant: 350).isActive = true
        portBackground.wantsLayer = true
        portBackground.layer?.cornerRadius = 7
        portBackground.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        portBackground.layer?.borderWidth = 1
        portBackground.layer?.borderColor = NSColor.separatorColor.cgColor
        portBackground.translatesAutoresizingMaskIntoConstraints = false
        portBackground.widthAnchor.constraint(equalToConstant: 350).isActive = true
        portBackground.heightAnchor.constraint(equalToConstant: 28).isActive = true
        port.isBordered = false
        port.drawsBackground = false
        port.focusRingType = .none
        port.translatesAutoresizingMaskIntoConstraints = false
        portBackground.addSubview(port)
        NSLayoutConstraint.activate([
            port.leadingAnchor.constraint(equalTo: portBackground.leadingAnchor, constant: 10),
            port.trailingAnchor.constraint(equalTo: portBackground.trailingAnchor, constant: -10),
            port.centerYAnchor.constraint(equalTo: portBackground.centerYAnchor)
        ])
        let networkLabel = NSTextField(labelWithString: "Network")
        let portLabel = NSTextField(labelWithString: "Port")
        for label in [networkLabel, portLabel] { label.widthAnchor.constraint(equalToConstant: 74).isActive = true }
        let networkRow = NSStackView(views: [networkLabel, networks]); networkRow.spacing = 16
        let portRow = NSStackView(views: [portLabel, portBackground]); portRow.spacing = 16
        advanced.orientation = .vertical; advanced.alignment = .leading; advanced.spacing = 12
        hint.textColor = .secondaryLabelColor
        for view in [networkRow, portRow, hint] { advanced.addArrangedSubview(view) }
        advanced.isHidden = true
        applyButton.target = self; applyButton.action = #selector(save)
        applyButton.bezelStyle = .rounded
        applyButton.bezelColor = .controlAccentColor
        applyButton.contentTintColor = .white
        applyButton.keyEquivalent = "\r"
        resetButton.target = self; resetButton.action = #selector(reset)
        let spacer = NSView()
        for view in [resetButton, spacer, applyButton] { buttons.addArrangedSubview(view) }
        buttons.spacing = 10; buttons.isHidden = true
        buttons.widthAnchor.constraint(equalToConstant: 440).isActive = true
        status.isHidden = true
        for view in [urlRow, status, disclosure, advanced, buttons] { stack.addArrangedSubview(view) }
        let container = NSView()
        container.addSubview(stack)
        window.contentView = container
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: container.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: container.topAnchor, constant: 18)
        ])
        window.center()
    }
    func present(_ preferences: NetworkPreferences, activePort: Int?, conflict: Bool) {
        current = preferences; port.stringValue = String(preferences.port)
        displayedPort = activePort ?? preferences.port
        networks.removeAllItems(); networks.addItem(withTitle: "Automatic"); ips = [""]
        var entries: UnsafeMutablePointer<ifaddrs>?
        if getifaddrs(&entries) == 0 {
            var cursor = entries
            while let entry = cursor {
                defer { cursor = entry.pointee.ifa_next }
                guard let addr = entry.pointee.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET), entry.pointee.ifa_flags & UInt32(IFF_UP) != 0, entry.pointee.ifa_flags & UInt32(IFF_LOOPBACK) == 0 else { continue }
                var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                if getnameinfo(addr, socklen_t(addr.pointee.sa_len), &buffer, socklen_t(buffer.count), nil, 0, NI_NUMERICHOST) == 0 {
                    let ip = String(cString: buffer)
                    ips.append(ip); networks.addItem(withTitle: "\(String(cString: entry.pointee.ifa_name)) — \(ip)")
                }
            }
            freeifaddrs(entries)
        }
        if !ips.contains(preferences.ip) { ips.append(preferences.ip); networks.addItem(withTitle: "Unavailable — \(preferences.ip)") }
        networks.selectItem(at: ips.firstIndex(of: preferences.ip) ?? 0)
        if conflict {
            disclosure.state = .on; advanced.isHidden = false; buttons.isHidden = false
            window.setContentSize(NSSize(width: 480, height: 225))
            hint.stringValue = "These ports are in use. Choose another port."
            hint.textColor = .systemRed
            portBackground.layer?.borderWidth = 1.5
            portBackground.layer?.borderColor = NSColor.systemRed.cgColor
        } else {
            portBackground.layer?.borderWidth = 1
            portBackground.layer?.borderColor = NSColor.separatorColor.cgColor
            hint.stringValue = "Applying changes will restart the server."
            hint.textColor = .secondaryLabelColor
        }
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        timer?.invalidate(); refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }
    func busy(_ value: Bool, message: String) {
        saving = value; status.stringValue = message
        status.isHidden = message == "Restarting…" || (!value && message == "Available")
        applyButton.title = value ? "Restarting…" : "Apply"
        applyButton.isEnabled = !value; resetButton.isEnabled = !value; networks.isEnabled = !value; port.isEnabled = !value
    }
    private func refresh() {
        guard !saving else { return }
        let request = URLRequest(url: URL(string: "http://127.0.0.1:\(displayedPort)/api/config")!, timeoutInterval: 2)
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            DispatchQueue.main.async {
                guard let self, !self.saving else { return }
                let config = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                self.address.stringValue = config?["remote_url"] as? String ?? "Unavailable"
                if config != nil { self.status.isHidden = true }
                else if self.status.stringValue == "Connecting…" { self.status.stringValue = "Server unavailable."; self.status.isHidden = false }
            }
        }.resume()
    }
    @objc private func save() {
        guard let number = Int(port.stringValue), (1...65535).contains(number) else { status.stringValue = "Port must be a number from 1 to 65535."; status.isHidden = false; return }
        apply?(NetworkPreferences(ip: ips[max(0, networks.indexOfSelectedItem)], port: number))
    }
    @objc private func reset() { networks.selectItem(at: 0); port.stringValue = "8765" }
    @objc private func copyAddress() { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(address.stringValue, forType: .string) }
    @objc private func toggleAdvanced(_ sender: NSButton) { advanced.isHidden = sender.state != .on; buttons.isHidden = advanced.isHidden; window.setContentSize(NSSize(width: 480, height: sender.state == .on ? 225 : 88)) }
    @objc private func closeWindow() { window.close() }
    func windowWillClose(_ notification: Notification) { timer?.invalidate(); timer = nil }
}
