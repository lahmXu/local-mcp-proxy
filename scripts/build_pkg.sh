#!/usr/bin/env bash
# Package an existing release directory into a macOS .pkg installer.
# Usage: sh scripts/build_pkg.sh [version]
# Example: sh scripts/build_pkg.sh 0.0.2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

APP_NAME="local-mcp-proxy"
APP_DISPLAY_NAME="Local MCP Proxy"
APP_EXECUTABLE="LocalMCPProxy"
APP_BUNDLE_NAME="${APP_DISPLAY_NAME}.app"
BUNDLE_IDENTIFIER="local.mcp.proxy"
VERSION="${1:-latest}"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
if [ "$OS" != "darwin" ]; then
    echo "错误: PKG 只能在 macOS 上生成，当前系统为: $OS" >&2
    exit 1
fi

for required_command in pkgbuild swiftc python3 sips iconutil; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "错误: 找不到 $required_command，无法生成 PKG" >&2
        exit 1
    fi
done

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
esac

DIST_NAME="dist-v${VERSION}-${OS}-${ARCH}"
DIST_DIR="$PROJECT_DIR/$DIST_NAME"
PKG_BUILD_DIR="$PROJECT_DIR/build/pkg/$DIST_NAME"
PKG_ROOT_DIR="$PKG_BUILD_DIR/root"
PKG_SCRIPTS_DIR="$PKG_BUILD_DIR/scripts"
APP_BUNDLE_DIR="$PKG_ROOT_DIR/Applications/$APP_BUNDLE_NAME"
ICON_BUILD_DIR="$PKG_BUILD_DIR/icons"
SWIFT_SOURCE="$PKG_BUILD_DIR/LocalMCPProxy.swift"
PKG_PATH="$DIST_DIR/${DIST_NAME}.pkg"

echo "执行 build.sh ..."
bash "$SCRIPT_DIR/build.sh" "$VERSION"

for required_path in \
    "$DIST_DIR/$APP_NAME" \
    "$DIST_DIR/configs"
do
    if [ ! -e "$required_path" ]; then
        echo "错误: 发布目录缺少必要文件: $required_path" >&2
        exit 1
    fi
done

echo "准备 PKG 构建目录..."
rm -rf "$PKG_BUILD_DIR" "$PKG_PATH"
mkdir -p \
    "$APP_BUNDLE_DIR/Contents/MacOS" \
    "$APP_BUNDLE_DIR/Contents/Resources/configs" \
    "$ICON_BUILD_DIR" \
    "$PKG_SCRIPTS_DIR"

cp "$DIST_DIR/$APP_NAME" "$APP_BUNDLE_DIR/Contents/Resources/"
cp -R "$DIST_DIR/configs/." "$APP_BUNDLE_DIR/Contents/Resources/configs/"
chmod +x "$APP_BUNDLE_DIR/Contents/Resources/$APP_NAME"

cat > "$APP_BUNDLE_DIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>${APP_DISPLAY_NAME}</string>
    <key>CFBundleExecutable</key>
    <string>${APP_EXECUTABLE}</string>
    <key>CFBundleIconFile</key>
    <string>app</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_IDENTIFIER}</string>
    <key>CFBundleName</key>
    <string>${APP_DISPLAY_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

python3 - "$ICON_BUILD_DIR/app.png" <<'PY'
import math
import struct
import sys
import zlib

output_path = sys.argv[1]
size = 1024
top = (20, 184, 140)
bottom = (16, 92, 170)
text_color = (245, 255, 248)
shadow_color = (6, 32, 55)

font = {
    "C": [
        "11111",
        "10000",
        "10000",
        "10000",
        "10000",
        "10000",
        "11111",
    ],
    "M": [
        "10001",
        "11011",
        "10101",
        "10101",
        "10001",
        "10001",
        "10001",
    ],
    "O": [
        "11111",
        "10001",
        "10001",
        "10001",
        "10001",
        "10001",
        "11111",
    ],
    "P": [
        "11110",
        "10001",
        "10001",
        "11110",
        "10000",
        "10000",
        "10000",
    ],
    "R": [
        "11110",
        "10001",
        "10001",
        "11110",
        "10100",
        "10010",
        "10001",
    ],
    "X": [
        "10001",
        "01010",
        "00100",
        "00100",
        "00100",
        "01010",
        "10001",
    ],
    "Y": [
        "10001",
        "01010",
        "00100",
        "00100",
        "00100",
        "00100",
        "00100",
    ],
}


def clamp(value):
    return max(0, min(255, int(value)))


def blend(base, overlay, alpha):
    return tuple(clamp(base[i] * (1 - alpha) + overlay[i] * alpha) for i in range(3))


def inside_rounded_rect(x, y, left, top_y, right, bottom_y, radius):
    if x < left or x >= right or y < top_y or y >= bottom_y:
        return False
    corner_x = left + radius if x < left + radius else right - radius - 1 if x >= right - radius else x
    corner_y = top_y + radius if y < top_y + radius else bottom_y - radius - 1 if y >= bottom_y - radius else y
    return (x - corner_x) ** 2 + (y - corner_y) ** 2 <= radius ** 2


def inside_play(x, y):
    return False


def text_pixel(x, y, text, start_x, start_y, scale):
    cursor_x = start_x
    for char in text:
        glyph = font[char]
        glyph_width = len(glyph[0]) * scale
        glyph_height = len(glyph) * scale
        if cursor_x <= x < cursor_x + glyph_width and start_y <= y < start_y + glyph_height:
            glyph_x = (x - cursor_x) // scale
            glyph_y = (y - start_y) // scale
            return glyph[glyph_y][glyph_x] == "1"
        cursor_x += glyph_width + scale
    return False


def text_width(text, scale):
    glyph_columns = sum(len(font[char][0]) for char in text)
    gaps = max(0, len(text) - 1)
    return (glyph_columns + gaps) * scale


def centered_x(text, scale):
    return (size - text_width(text, scale)) // 2


mcp_text = "MCP"
proxy_text = "PROXY"
mcp_scale = 48
proxy_scale = 22
mcp_x = centered_x(mcp_text, mcp_scale)
proxy_x = centered_x(proxy_text, proxy_scale)
mcp_y = 250
proxy_y = 622
shadow_offset = 9


rows = []
for y in range(size):
    row = bytearray()
    row.append(0)
    vertical = y / (size - 1)
    base = tuple(clamp(top[i] * (1 - vertical) + bottom[i] * vertical) for i in range(3))
    for x in range(size):
        if not inside_rounded_rect(x, y, 64, 64, 960, 960, 192):
            row.extend((0, 0, 0, 0))
            continue

        color = base
        distance = math.sqrt((x - 512) ** 2 + (y - 430) ** 2) / 620
        color = blend(color, (255, 255, 255), max(0, 1 - distance) * 0.18)

        for cx, cy in ((300, 330), (724, 348), (276, 700), (740, 700)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= 18 ** 2:
                color = blend(color, (255, 255, 255), 0.25)
        if 330 < y < 700 and abs((x - 300) - (y - 330) * 424 / 370) < 3:
            color = blend(color, (255, 255, 255), 0.12)
        if 348 < y < 700 and abs((x - 724) + (y - 348) * 448 / 352) < 3:
            color = blend(color, (255, 255, 255), 0.12)

        if text_pixel(x, y, mcp_text, mcp_x, mcp_y, mcp_scale) or text_pixel(x, y, proxy_text, proxy_x, proxy_y, proxy_scale):
            color = text_color
        elif text_pixel(x, y, mcp_text, mcp_x + shadow_offset, mcp_y + shadow_offset, mcp_scale) or text_pixel(x, y, proxy_text, proxy_x + shadow_offset, proxy_y + shadow_offset, proxy_scale):
            color = blend(color, shadow_color, 0.45)

        row.extend((*color, 255))
    rows.append(bytes(row))


def chunk(name, data):
    return (
        struct.pack(">I", len(data))
        + name
        + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    )


raw = b"".join(rows)
png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(raw, 9))
    + chunk(b"IEND", b"")
)

with open(output_path, "wb") as output:
    output.write(png)
PY

ICONSET_DIR="$ICON_BUILD_DIR/app.iconset"
mkdir -p "$ICONSET_DIR"
sips -z 16 16 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$ICON_BUILD_DIR/app.png" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET_DIR" -o "$APP_BUNDLE_DIR/Contents/Resources/app.icns"

cat > "$SWIFT_SOURCE" <<'SWIFT'
import AppKit
import Foundation

private enum ServiceState: Equatable {
    case stopped
    case starting
    case running
    case stopping
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var serviceProcess: Process?
    private var isStoppingService = false
    private var serviceState: ServiceState = .stopped
    private var readinessTimer: Timer?
    private var readinessAttempts = 0
    private let maxReadinessAttempts = 120
    private var statusItem: NSStatusItem?
    private var statusMenuItems: [NSMenuItem] = []
    private var startMenuItems: [NSMenuItem] = []
    private var stopMenuItems: [NSMenuItem] = []
    private var restartMenuItems: [NSMenuItem] = []
    private let webURL = URL(string: "http://127.0.0.1:9211")!
    private let healthURL = URL(string: "http://127.0.0.1:9211/api/check-auth")!
    private let mcpURL = "http://127.0.0.1:9210/mcp"
    private let fileManager = FileManager.default
    private lazy var supportDir = fileManager.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/local-mcp-proxy", isDirectory: true)
    private lazy var configDir = supportDir.appendingPathComponent("configs", isDirectory: true)
    private lazy var logDir = supportDir.appendingPathComponent("logs", isDirectory: true)
    private lazy var tempDir = supportDir.appendingPathComponent("tmp", isDirectory: true)
    private lazy var logFile = logDir.appendingPathComponent("server.log")
    private lazy var pidFile = supportDir.appendingPathComponent("local-mcp-proxy.pid")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureMenu()
        configureStatusItem()
        updateServiceState(.stopped)
        startService()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        stopService(showNotification: false)
        return .terminateNow
    }

    private func configureMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)

        appMenuItem.submenu = buildControlMenu(includeAppName: true)
        NSApp.mainMenu = mainMenu
    }

    private func configureStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.imagePosition = .imageOnly
        item.button?.toolTip = "Local MCP Proxy"
        item.menu = buildControlMenu(includeAppName: false)
        statusItem = item
    }

    private func buildControlMenu(includeAppName: Bool) -> NSMenu {
        let menu = NSMenu(title: includeAppName ? "Local MCP Proxy" : "")
        menu.delegate = self
        let statusItem = NSMenuItem(title: "状态：未启动", action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        statusMenuItems.append(statusItem)
        menu.addItem(statusItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(makeMenuItem(title: "打开管理页面", action: #selector(openAdminPage), keyEquivalent: includeAppName ? "o" : ""))
        menu.addItem(makeMenuItem(title: "查看日志", action: #selector(openLogFile), keyEquivalent: includeAppName ? "l" : ""))
        menu.addItem(NSMenuItem.separator())
        let startItem = makeMenuItem(title: "启动服务", action: #selector(startServiceFromMenu), keyEquivalent: includeAppName ? "s" : "")
        let stopItem = makeMenuItem(title: "停止服务", action: #selector(stopServiceFromMenu), keyEquivalent: includeAppName ? "t" : "")
        let restartItem = makeMenuItem(title: "重启服务", action: #selector(restartServiceFromMenu), keyEquivalent: includeAppName ? "r" : "")
        startMenuItems.append(startItem)
        stopMenuItems.append(stopItem)
        restartMenuItems.append(restartItem)
        menu.addItem(startItem)
        menu.addItem(stopItem)
        menu.addItem(restartItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(makeMenuItem(title: "退出 Local MCP Proxy", action: #selector(quit), keyEquivalent: includeAppName ? "q" : ""))
        return menu
    }

    func menuWillOpen(_ menu: NSMenu) {
        refreshServiceStateFromProcess()
    }

    private func makeMenuItem(title: String, action: Selector, keyEquivalent: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: keyEquivalent)
        item.target = self
        return item
    }

    private func updateServiceState(_ state: ServiceState) {
        serviceState = state
        statusItem?.button?.image = makeStatusIcon(state: state)
        statusItem?.button?.toolTip = statusTooltip(for: state)
        statusMenuItems.forEach { $0.title = "状态：\(statusTitle(for: state))" }
        startMenuItems.forEach { $0.isEnabled = state == .stopped }
        stopMenuItems.forEach { $0.isEnabled = state == .starting || state == .running }
        restartMenuItems.forEach { $0.isEnabled = state == .running }
    }

    private func statusTitle(for state: ServiceState) -> String {
        switch state {
        case .stopped:
            return "未启动"
        case .starting:
            return "启动中"
        case .running:
            return "运行中"
        case .stopping:
            return "停止中"
        }
    }

    private func statusTooltip(for state: ServiceState) -> String {
        "Local MCP Proxy \(statusTitle(for: state))"
    }

    private func makeStatusIcon(state: ServiceState) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size)
        image.lockFocus()

        NSColor.clear.setFill()
        NSRect(origin: .zero, size: size).fill()

        let baseColor: NSColor
        switch state {
        case .stopped:
            baseColor = NSColor(calibratedWhite: 0.55, alpha: 1.0)
        case .starting:
            baseColor = NSColor(calibratedRed: 0.95, green: 0.62, blue: 0.18, alpha: 1.0)
        case .running:
            baseColor = NSColor(calibratedRed: 0.08, green: 0.72, blue: 0.52, alpha: 1.0)
        case .stopping:
            baseColor = NSColor(calibratedRed: 0.88, green: 0.36, blue: 0.32, alpha: 1.0)
        }
        let strokeColor = NSColor(calibratedWhite: 1.0, alpha: 0.85)

        baseColor.setFill()
        let outerCircle = NSBezierPath(ovalIn: NSRect(x: 2.5, y: 2.5, width: 13, height: 13))
        outerCircle.fill()

        strokeColor.setStroke()
        outerCircle.lineWidth = 1.2
        outerCircle.stroke()

        // Draw a compact proxy/network glyph instead of text.
        strokeColor.setStroke()
        let center = NSPoint(x: 9, y: 9)
        let nodes = [
            NSPoint(x: 6, y: 11.5),
            NSPoint(x: 12, y: 11.5),
            NSPoint(x: 9, y: 6),
        ]

        for node in nodes {
            let line = NSBezierPath()
            line.move(to: center)
            line.line(to: node)
            line.lineWidth = 1.1
            line.stroke()
        }

        strokeColor.setFill()
        for node in nodes + [center] {
            NSBezierPath(ovalIn: NSRect(x: node.x - 1.15, y: node.y - 1.15, width: 2.3, height: 2.3)).fill()
        }

        image.unlockFocus()
        image.isTemplate = false
        return image
    }

    @objc private func openAdminPage() {
        NSWorkspace.shared.open(webURL)
    }

    @objc private func openLogFile() {
        ensureSupportDirectories()
        if !fileManager.fileExists(atPath: logFile.path) {
            fileManager.createFile(atPath: logFile.path, contents: nil)
        }
        NSWorkspace.shared.open(logFile)
    }

    @objc private func startServiceFromMenu() {
        startService()
    }

    @objc private func stopServiceFromMenu() {
        stopService(showNotification: false)
    }

    @objc private func restartServiceFromMenu() {
        stopService(showNotification: false)
        startService()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func startService() {
        if let process = serviceProcess, process.isRunning {
            updateServiceState(serviceState)
            return
        }

        isStoppingService = false
        ensureSupportDirectories()
        copyInitialConfigs()

        guard let binaryURL = Bundle.main.url(forResource: "local-mcp-proxy", withExtension: nil) else {
            showError(title: "启动失败", message: "找不到 local-mcp-proxy 可执行文件。")
            return
        }

        let process = Process()
        process.executableURL = binaryURL
        process.arguments = [
            "--config-dir", configDir.path,
            "--mcp-transport", "streamable-http",
            "--mcp-host", "127.0.0.1",
            "--mcp-port", "9210",
            "--web-host", "127.0.0.1",
            "--web-port", "9211",
        ]
        var environment = ProcessInfo.processInfo.environment
        environment["TMPDIR"] = tempDir.path
        environment["TMP"] = tempDir.path
        environment["TEMP"] = tempDir.path
        process.environment = environment

        do {
            let logHandle = try FileHandle(forWritingTo: logFile)
            try logHandle.seekToEnd()
            process.standardOutput = logHandle
            process.standardError = logHandle
            process.terminationHandler = { [weak self] terminatedProcess in
                DispatchQueue.main.async {
                    self?.handleServiceExit(terminatedProcess)
                }
            }
            try process.run()
            serviceProcess = process
            try "\(process.processIdentifier)\n".write(to: pidFile, atomically: true, encoding: .utf8)
            updateServiceState(.starting)
            beginReadinessCheck()
        } catch {
            updateServiceState(.stopped)
            showError(title: "启动失败", message: "无法启动 local-mcp-proxy：\(error.localizedDescription)")
        }
    }

    private func stopService(showNotification: Bool) {
        guard let process = serviceProcess, process.isRunning else {
            removePidFile()
            invalidateReadinessCheck()
            updateServiceState(.stopped)
            if showNotification {
                showInfo(title: "Local MCP Proxy", message: "服务未运行。")
            }
            return
        }

        isStoppingService = true
        invalidateReadinessCheck()
        updateServiceState(.stopping)
        process.terminate()
        let deadline = Date().addingTimeInterval(5)
        while process.isRunning && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }

        if process.isRunning {
            kill(process.processIdentifier, SIGKILL)
        }

        removePidFile()
        serviceProcess = nil
        isStoppingService = false
        updateServiceState(.stopped)

        if showNotification {
            showInfo(title: "Local MCP Proxy", message: "服务已停止。")
        }
    }

    private func refreshServiceStateFromProcess() {
        if let process = serviceProcess, process.isRunning {
            if serviceState == .stopped {
                updateServiceState(.running)
            } else {
                updateServiceState(serviceState)
            }
            return
        }

        serviceProcess = nil
        removePidFile()
        updateServiceState(.stopped)
    }

    private func handleServiceExit(_ process: Process) {
        guard serviceProcess === process else {
            return
        }
        let expectedStop = isStoppingService
        invalidateReadinessCheck()
        removePidFile()
        serviceProcess = nil
        isStoppingService = false
        updateServiceState(.stopped)
        if expectedStop {
            return
        }
        if process.terminationStatus != 0 {
            showError(
                title: "服务已退出",
                message: "local-mcp-proxy 异常退出，退出码：\(process.terminationStatus)。请查看日志：\(logFile.path)"
            )
        }
    }

    private func beginReadinessCheck() {
        invalidateReadinessCheck()
        readinessAttempts = 0
        readinessTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.checkReadiness()
        }
    }

    private func invalidateReadinessCheck() {
        readinessTimer?.invalidate()
        readinessTimer = nil
        readinessAttempts = 0
    }

    private func checkReadiness() {
        guard let process = serviceProcess, process.isRunning else {
            invalidateReadinessCheck()
            updateServiceState(.stopped)
            return
        }

        readinessAttempts += 1
        if readinessAttempts > maxReadinessAttempts {
            invalidateReadinessCheck()
            stopService(showNotification: false)
            showError(title: "启动超时", message: "服务进程已启动，但管理页面 60 秒内未就绪。请查看日志：\(logFile.path)")
            return
        }

        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            guard let self else {
                return
            }
            guard let httpResponse = response as? HTTPURLResponse, (200..<500).contains(httpResponse.statusCode) else {
                return
            }
            DispatchQueue.main.async {
                self.invalidateReadinessCheck()
                if let process = self.serviceProcess, process.isRunning {
                    self.updateServiceState(.running)
                }
            }
        }.resume()
    }

    private func ensureSupportDirectories() {
        do {
            try fileManager.createDirectory(at: configDir, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: logDir, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: tempDir, withIntermediateDirectories: true)
            if !fileManager.fileExists(atPath: logFile.path) {
                fileManager.createFile(atPath: logFile.path, contents: nil)
            }
        } catch {
            showError(title: "目录创建失败", message: error.localizedDescription)
        }
    }

    private func copyInitialConfigs() {
        guard let bundledConfigDir = Bundle.main.resourceURL?.appendingPathComponent("configs", isDirectory: true) else {
            return
        }
        guard let configFiles = try? fileManager.contentsOfDirectory(at: bundledConfigDir, includingPropertiesForKeys: nil) else {
            return
        }

        for source in configFiles {
            let target = configDir.appendingPathComponent(source.lastPathComponent)
            if !fileManager.fileExists(atPath: target.path) {
                do {
                    try fileManager.copyItem(at: source, to: target)
                } catch {
                    showError(title: "配置复制失败", message: "\(source.lastPathComponent): \(error.localizedDescription)")
                }
            }
        }
    }

    private func removePidFile() {
        try? fileManager.removeItem(at: pidFile)
    }

    private func showError(title: String, message: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = title
        alert.informativeText = message
        alert.runModal()
    }

    private func showInfo(title: String, message: String) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = title
        alert.informativeText = message
        alert.runModal()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
SWIFT

swiftc "$SWIFT_SOURCE" \
    -framework AppKit \
    -o "$APP_BUNDLE_DIR/Contents/MacOS/$APP_EXECUTABLE"

cat > "$PKG_SCRIPTS_DIR/postinstall" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

exit 0
EOF
chmod +x "$PKG_SCRIPTS_DIR/postinstall"

echo "创建 PKG: $PKG_PATH"
pkgbuild \
    --root "$PKG_ROOT_DIR" \
    --scripts "$PKG_SCRIPTS_DIR" \
    --identifier "$BUNDLE_IDENTIFIER" \
    --version "$VERSION" \
    --install-location "/" \
    "$PKG_PATH"

rm -rf "$PKG_BUILD_DIR"

echo ""
echo "完成: $PKG_PATH"
