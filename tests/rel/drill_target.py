"""这是什么：watchdog 实杀实拉演练的目标进程（REL-01 §9.2-2）。
用法：python -m tests.rel.drill_target <port>
行为：在 127.0.0.1:<port> 起一个最小 HTTP 服务，GET /api/health 恒返 200——
     与控制台 /api/health 的探活语义一致，用于真实 kill -> 自动拉起演练。
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"version":"drill","db":true,"events":true,"config":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音访问日志
        pass


def main() -> int:
    port = int(sys.argv[1])
    server = HTTPServer(("127.0.0.1", port), _Health)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
