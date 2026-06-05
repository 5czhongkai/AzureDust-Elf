import Cocoa
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow?
    private var webView: WKWebView?
    private var serverProcess: Process?
    private var serverStartedByApp = false
    private var logHandle: FileHandle?
    private var projectRoot = URL(fileURLWithPath: ".")
    private var retryCount = 0
    private let maxRetries = 60

    private var environment: [String: String] {
        ProcessInfo.processInfo.environment
    }

    private var host: String {
        let configured = environment["CONTENT_AGENT_CONSOLE_HOST"] ?? ""
        return configured.isEmpty ? "127.0.0.1" : configured
    }

    private var port: Int {
        Int(environment["CONTENT_AGENT_CONSOLE_PORT"] ?? "8091") ?? 8091
    }

    private var consoleURL: URL {
        URL(string: "http://\(host):\(port)/")!
    }

    private var healthURL: URL {
        URL(string: "http://\(host):\(port)/healthz")!
    }

    private var logURL: URL {
        projectRoot
            .appendingPathComponent("outputs", isDirectory: true)
            .appendingPathComponent("runs", isDirectory: true)
            .appendingPathComponent("_state", isDirectory: true)
            .appendingPathComponent("desktop_app_console.log")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        projectRoot = resolveProjectRoot()
        configureMenu()
        createWindow()
        showLoading(message: "正在准备本机创作工作台...")
        ensureConsoleIsRunning()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if serverStartedByApp, let process = serverProcess, process.isRunning {
            process.terminate()
        }
        try? logHandle?.close()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showFailure("窗口加载失败", detail: error.localizedDescription)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showFailure("窗口加载失败", detail: error.localizedDescription)
    }

    private func resolveProjectRoot() -> URL {
        if let configured = environment["CONTENT_AGENT_PROJECT_ROOT"], !configured.isEmpty {
            return URL(fileURLWithPath: configured)
        }

        let bundleParent = Bundle.main.bundleURL.deletingLastPathComponent()
        if FileManager.default.fileExists(atPath: bundleParent.appendingPathComponent("Makefile").path) {
            return bundleParent
        }

        return URL(fileURLWithPath: "/Volumes/D/自媒体内容创作")
    }

    private func configureMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(
            withTitle: "退出 自媒体内容创作",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)
        NSApp.mainMenu = mainMenu
    }

    private func createWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1240, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "自媒体内容创作工作台"
        window.minSize = NSSize(width: 980, height: 680)
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)

        self.webView = webView
        self.window = window
    }

    private func ensureConsoleIsRunning() {
        checkHealth { [weak self] healthy in
            DispatchQueue.main.async {
                guard let self else { return }
                if healthy {
                    self.loadConsole()
                    return
                }
                self.startConsoleServer()
                self.waitForConsole()
            }
        }
    }

    private func startConsoleServer() {
        guard serverProcess == nil else { return }

        let stateDirectory = logURL.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil)
            }
            logHandle = try FileHandle(forWritingTo: logURL)
            try logHandle?.seekToEnd()
        } catch {
            showFailure("无法创建本机日志", detail: "\(logURL.path)\n\(error.localizedDescription)")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-lc", "make console CONSOLE_PORT=\(port) CONSOLE_HOST=\(host)"]
        process.currentDirectoryURL = projectRoot

        var processEnvironment = environment
        processEnvironment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        processEnvironment["CONTENT_AGENT_DESKTOP_APP"] = "1"
        process.environment = processEnvironment
        process.standardOutput = logHandle
        process.standardError = logHandle

        do {
            try process.run()
            serverProcess = process
            serverStartedByApp = true
        } catch {
            showFailure("无法启动本机服务", detail: "\(error.localizedDescription)\n项目目录：\(projectRoot.path)")
        }
    }

    private func waitForConsole() {
        retryCount += 1
        showLoading(message: "正在启动本机服务... \(retryCount)/\(maxRetries)")

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { [weak self] in
            guard let self else { return }
            self.checkHealth { healthy in
                DispatchQueue.main.async {
                    if healthy {
                        self.loadConsole()
                    } else if self.retryCount < self.maxRetries {
                        self.waitForConsole()
                    } else {
                        self.showFailure(
                            "本机服务未能启动",
                            detail: "请查看日志：\(self.logURL.path)\n也可以在项目目录手动运行：make console CONSOLE_PORT=\(self.port)"
                        )
                    }
                }
            }
        }
    }

    private func checkHealth(completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 0.8

        URLSession.shared.dataTask(with: request) { _, response, _ in
            guard let httpResponse = response as? HTTPURLResponse else {
                completion(false)
                return
            }
            completion((200..<300).contains(httpResponse.statusCode))
        }.resume()
    }

    private func loadConsole() {
        window?.title = "自媒体内容创作工作台"
        webView?.load(URLRequest(url: consoleURL))
    }

    private func showLoading(message: String) {
        showHTML(
            title: "自媒体内容创作工作台",
            heading: "正在打开工作台",
            body: message,
            detail: "服务地址：\(consoleURL.absoluteString)"
        )
    }

    private func showFailure(_ heading: String, detail: String) {
        showHTML(
            title: "启动失败",
            heading: heading,
            body: "桌面启动器没有完成本机工作台启动。",
            detail: detail
        )
    }

    private func showHTML(title: String, heading: String, body: String, detail: String) {
        let html = """
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>\(escapeHTML(title))</title>
          <style>
            :root {
              color-scheme: light;
              --ink: #172033;
              --muted: #667085;
              --line: #d8dee8;
              --paper: #f6f8fb;
              --accent: #1f7a6d;
              --accent-2: #2f5f9f;
            }
            * { box-sizing: border-box; }
            body {
              margin: 0;
              min-height: 100vh;
              display: grid;
              place-items: center;
              background:
                linear-gradient(135deg, rgba(31, 122, 109, 0.12), rgba(47, 95, 159, 0.10)),
                var(--paper);
              color: var(--ink);
              font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", Arial, sans-serif;
            }
            main {
              width: min(560px, calc(100vw - 48px));
              border: 1px solid var(--line);
              border-radius: 8px;
              background: rgba(255, 255, 255, 0.88);
              padding: 28px;
              box-shadow: 0 18px 52px rgba(23, 32, 51, 0.12);
            }
            .mark {
              width: 48px;
              height: 48px;
              border-radius: 8px;
              display: grid;
              place-items: center;
              background: linear-gradient(145deg, var(--accent), var(--accent-2));
              color: white;
              font-weight: 800;
              font-size: 20px;
              margin-bottom: 18px;
            }
            h1 {
              font-size: 24px;
              line-height: 1.25;
              margin: 0 0 10px;
              letter-spacing: 0;
            }
            p {
              margin: 0;
              line-height: 1.7;
              color: var(--muted);
              font-size: 14px;
            }
            pre {
              margin: 18px 0 0;
              padding: 14px;
              border-radius: 8px;
              background: #101828;
              color: #e6eef8;
              white-space: pre-wrap;
              word-break: break-word;
              font-size: 12px;
              line-height: 1.55;
            }
          </style>
        </head>
        <body>
          <main>
            <div class="mark">创</div>
            <h1>\(escapeHTML(heading))</h1>
            <p>\(escapeHTML(body))</p>
            <pre>\(escapeHTML(detail))</pre>
          </main>
        </body>
        </html>
        """
        webView?.loadHTMLString(html, baseURL: nil)
    }

    private func escapeHTML(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#39;")
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
