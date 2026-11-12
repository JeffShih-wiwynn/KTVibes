import Cocoa
import Foundation
import CommonCrypto
import Security

struct NetworkPreferences: Codable, Equatable {
    var ip: String = ""
    var port: Int = 8765
    var external_url: String? = nil
    var password_hash: String? = nil
    var credential_type: String? = nil
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
    var desktopToken = ""
    private let external = NSButton(checkboxWithTitle: "External address", target: nil, action: nil)
    private let externalURL = NSTextField(string: "")
    private let password = NSSecureTextField(string: "")
    private let externalFields = NSStackView()
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
        external.target = self; external.action = #selector(toggleExternal)
        externalURL.placeholderString = "https://ktv.example.com"
        password.placeholderString = "PIN: at least 6 digits; blank keeps existing PIN"
        externalFields.orientation = .vertical; externalFields.spacing = 12
        for view in [externalURL, password] { externalFields.addArrangedSubview(Self.fieldBackground(view, width: 440)) }
        externalFields.isHidden = true
        for view in [networkRow, portRow, external, externalFields, hint] { advanced.addArrangedSubview(view) }
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
    private static func fieldBackground(_ field: NSTextField, width: CGFloat) -> NSView {
        let background = NSView(); background.wantsLayer = true
        background.layer?.cornerRadius = 7; background.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        background.layer?.borderWidth = 1; background.layer?.borderColor = NSColor.separatorColor.cgColor
        background.translatesAutoresizingMaskIntoConstraints = false
        background.widthAnchor.constraint(equalToConstant: width).isActive = true
        background.heightAnchor.constraint(equalToConstant: 28).isActive = true
        field.isBordered = false; field.drawsBackground = false; field.focusRingType = .none
        field.translatesAutoresizingMaskIntoConstraints = false; background.addSubview(field)
        NSLayoutConstraint.activate([field.leadingAnchor.constraint(equalTo: background.leadingAnchor, constant: 10), field.trailingAnchor.constraint(equalTo: background.trailingAnchor, constant: -10), field.centerYAnchor.constraint(equalTo: background.centerYAnchor)])
        return background
    }
    func present(_ preferences: NetworkPreferences, activePort: Int?, conflict: Bool) {
        external.state = (preferences.external_url ?? "").isEmpty ? .off : .on
        externalURL.stringValue = preferences.external_url ?? ""; password.stringValue = ""
        externalFields.isHidden = external.state != .on
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
        if external.state == .on && preferences.credential_type != "pin" {
            hint.stringValue = "Set a new PIN before applying. Your old password still works until then."
        }
        resize(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        timer?.invalidate(); refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }
    func busy(_ value: Bool, message: String) {
        saving = value; status.stringValue = message
        status.isHidden = message == "Restarting…" || (!value && message == "Available")
        applyButton.title = value ? "Restarting…" : "Apply"
        applyButton.isEnabled = !value; resetButton.isEnabled = !value; networks.isEnabled = !value; port.isEnabled = !value; external.isEnabled = !value; externalURL.isEnabled = !value; password.isEnabled = !value
    }
    private func refresh() {
        guard !saving else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(displayedPort)/api/config")!, timeoutInterval: 2)
        request.setValue("Bearer " + desktopToken, forHTTPHeaderField: "Authorization")
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
        var next = NetworkPreferences(ip: ips[max(0, networks.indexOfSelectedItem)], port: number)
        if external.state == .on {
            let text = externalURL.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let url = URLComponents(string: text), url.scheme == "https", !(url.host ?? "").isEmpty, url.user == nil, url.password == nil, url.query == nil, url.fragment == nil, ["", "/", "/remote"].contains(url.path) else { status.stringValue = "Enter an HTTPS address, optionally ending in /remote."; status.isHidden = false; return }
            guard !password.stringValue.isEmpty || (!(current.password_hash ?? "").isEmpty && current.credential_type == "pin") else { status.stringValue = "Set a new PIN of at least 6 digits."; status.isHidden = false; return }
            if !password.stringValue.isEmpty && (password.stringValue.count < 6 || password.stringValue.utf8.count > 1024 || !password.stringValue.utf8.allSatisfy { (48...57).contains($0) }) { status.stringValue = "Use at least 6 digits (0–9)."; status.isHidden = false; return }
            next.credential_type = "pin"
            next.external_url = text
            next.password_hash = password.stringValue.isEmpty ? current.password_hash : Self.hashPassword(password.stringValue)
        }
        password.stringValue = ""
        apply?(next)
    }
    private static func hashPassword(_ password: String) -> String {
        var salt = [UInt8](repeating: 0, count: 16)
        guard SecRandomCopyBytes(kSecRandomDefault, salt.count, &salt) == errSecSuccess else { fatalError("Secure random source unavailable") }
        let bytes = Array(password.utf8)
        var output = [UInt8](repeating: 0, count: 32)
        let result = bytes.withUnsafeBytes { input in salt.withUnsafeBytes { saltBytes in output.withUnsafeMutableBytes { out in
            CCKeyDerivationPBKDF(CCPBKDFAlgorithm(kCCPBKDF2), input.baseAddress!.assumingMemoryBound(to: Int8.self), bytes.count, saltBytes.baseAddress!.assumingMemoryBound(to: UInt8.self), 16, CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256), 600000, out.baseAddress!.assumingMemoryBound(to: UInt8.self), 32)
        } } }
        precondition(result == kCCSuccess)
        let hex: ([UInt8]) -> String = { $0.map { String(format: "%02x", $0) }.joined() }
        return "pbkdf2-sha256$600000$" + hex(salt) + "$" + hex(output)
    }
    private func resize() { window.setContentSize(NSSize(width: 480, height: disclosure.state == .on ? (external.state == .on ? 345 : 260) : 88)) }
    @objc private func toggleExternal() { externalFields.isHidden = external.state != .on; resize() }
    @objc private func reset() { networks.selectItem(at: 0); port.stringValue = "8765"; external.state = .off; externalURL.stringValue = ""; password.stringValue = ""; toggleExternal() }
    @objc private func copyAddress() { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(address.stringValue, forType: .string) }
    @objc private func toggleAdvanced(_ sender: NSButton) { advanced.isHidden = sender.state != .on; buttons.isHidden = advanced.isHidden; resize() }
    @objc private func closeWindow() { window.close() }
    func windowWillClose(_ notification: Notification) { timer?.invalidate(); timer = nil }
}
