"""Boundary evidence: httpx2's shared connection pool holds under free-threaded parallelism.

httpware can't self-certify httpx2, so this is living regression evidence. Each request is
verified against its response to catch pool cross-talk. Uses a real loopback server because a
mock transport bypasses the pool this test exists to stress.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

_N_THREADS = 16
_N_REQ = 100


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = self.path.rsplit("/", 1)[-1].encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence server logs
        pass


@pytest.mark.stress
def test_httpx2_shared_pool_no_crosstalk_under_parallelism() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results: list[tuple[int, int, str]] = []
    guard = threading.Lock()

    client = httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0)

    def worker(tid: int) -> None:
        for i in range(_N_REQ):
            n = tid * _N_REQ + i
            r = client.get(f"/echo/{n}")
            with guard:  # runs every request, so the recording stays covered
                results.append((n, r.status_code, r.text))

    try:
        with ThreadPoolExecutor(max_workers=_N_THREADS) as ex:
            list(ex.map(worker, range(_N_THREADS)))
    finally:
        client.close()
        server.shutdown()

    # Every response must echo its own request's number; a mismatch is pool cross-talk.
    mismatches = [(n, status, text) for n, status, text in results if status != 200 or text != str(n)]
    assert mismatches == []
