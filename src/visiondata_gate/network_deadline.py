"""Absolute HTTP attempt deadlines without uncancellable request workers.

Only DNS may outlive its caller. Four process-wide daemon workers and a bounded
queue contain a stuck platform resolver; a DNS job never receives request data
or credentials and cannot initiate a connection when it eventually completes.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import http.client
import queue
import socket
import ssl
import threading
import time
from typing import Any, Iterator
import urllib.error
import urllib.request


Address = tuple[int, int, int, str, tuple[Any, ...]]
_DNS_WORKERS = 4


class AttemptDeadline:
    """Own a socket and interrupt all of its I/O at one real-time deadline."""

    def __init__(self, seconds: float) -> None:
        # Circuit tests can inject a frozen clock; network time must still pass.
        self.expires_at = time.monotonic() + seconds
        self._expired = threading.Event()
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True
        self._timer.name = "visiondata-http-deadline"

    def remaining(self) -> float:
        remaining = self.expires_at - time.monotonic()
        if self._expired.is_set() or remaining <= 0:
            raise TimeoutError("request deadline exceeded")
        return remaining

    def bind(self, sock: socket.socket) -> None:
        with self._lock:
            try:
                sock.settimeout(self.remaining())
            except BaseException:
                sock.close()
                raise
            self._socket = sock

    def _expire(self) -> None:
        self._expired.set()
        with self._lock:
            if self._socket is not None:
                # close() alone does not interrupt a socket held by makefile().
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._socket.close()

    def __enter__(self) -> AttemptDeadline:
        self._timer.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._timer.cancel()
        self._timer.join()
        with self._lock:
            if self._socket is not None:
                self._socket.close()
                self._socket = None
        # A watchdog-induced EOF, SSL error, or socket-close error is a timeout.
        self.remaining()


@dataclass
class _DNSJob:
    host: str
    port: int
    expires_at: float
    done: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    addresses: list[Address] = field(default_factory=list)
    error: Exception | None = None


_dns_jobs: queue.Queue[_DNSJob] = queue.Queue(maxsize=_DNS_WORKERS)
_dns_start_lock = threading.Lock()
_dns_started = False


def _dns_worker() -> None:
    while True:
        job = _dns_jobs.get()
        try:
            if not job.cancelled.is_set() and time.monotonic() < job.expires_at:
                try:
                    job.addresses = socket.getaddrinfo(
                        job.host, job.port, type=socket.SOCK_STREAM
                    )
                except Exception as error:
                    job.error = error
        finally:
            job.done.set()
            _dns_jobs.task_done()


def resolve_addresses(host: str, port: int, deadline: AttemptDeadline) -> list[Address]:
    global _dns_started
    with _dns_start_lock:
        if not _dns_started:
            for index in range(_DNS_WORKERS):
                threading.Thread(
                    target=_dns_worker,
                    name=f"visiondata-dns-{index}",
                    daemon=True,
                ).start()
            _dns_started = True
    job = _DNSJob(host, port, deadline.expires_at)
    try:
        try:
            _dns_jobs.put(job, timeout=deadline.remaining())
        except queue.Full as error:
            raise TimeoutError("request deadline exceeded") from error
        if not job.done.wait(deadline.remaining()):
            raise TimeoutError("request deadline exceeded")
        deadline.remaining()
        if job.error is not None:
            if isinstance(job.error, socket.gaierror):
                raise ConnectionError("endpoint DNS resolution failed") from job.error
            raise job.error
        if not job.addresses:
            raise ConnectionError("endpoint DNS resolution returned no addresses")
        return job.addresses
    finally:
        job.cancelled.set()


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        secure: bool,
        addresses: list[Address],
        deadline: AttemptDeadline,
    ) -> None:
        super().__init__(host, port, timeout=deadline.remaining())
        self._addresses = addresses
        self._deadline = deadline
        self._context = ssl.create_default_context() if secure else None
        if self._context is not None:
            self._context.set_alpn_protocols(["http/1.1"])

    def connect(self) -> None:
        # Never resolve the hostname again after destination-policy validation.
        last_error: OSError | None = None
        for family, kind, protocol, _name, address in self._addresses:
            self._deadline.remaining()
            sock = socket.socket(family, kind, protocol)
            try:
                self._deadline.bind(sock)
                sock.connect(address)
                self._deadline.remaining()
                if self._context is not None:
                    sock = self._context.wrap_socket(
                        sock, server_hostname=self.host, do_handshake_on_connect=False
                    )
                    self._deadline.bind(sock)
                    sock.do_handshake()
                    self._deadline.remaining()
                self.sock = sock
                return
            except OSError as error:
                sock.close()
                self._deadline.remaining()
                last_error = error
        if last_error is not None:
            raise last_error
        raise ConnectionError("endpoint has no connectable address")


@contextmanager
def open_response(
    request: urllib.request.Request,
    *,
    host: str,
    port: int,
    secure: bool,
    addresses: list[Address],
    deadline: AttemptDeadline,
) -> Iterator[http.client.HTTPResponse]:
    # Direct HTTPConnection intentionally has no environment-proxy or redirect
    # machinery. Keep the hostname for Host, SNI and certificate verification.
    connection = _PinnedConnection(
        host, port, secure=secure, addresses=addresses, deadline=deadline
    )
    try:
        deadline.remaining()
        connection.request(
            request.get_method(),
            request.selector,
            body=request.data,
            headers={**dict(request.header_items()), "Connection": "close"},
        )
        deadline.remaining()
        response = connection.getresponse()
        try:
            deadline.remaining()
            if not 200 <= response.status < 300:
                raise urllib.error.HTTPError(
                    request.full_url,
                    response.status,
                    response.reason,
                    response.headers,
                    None,
                )
            yield response
            deadline.remaining()
        finally:
            response.close()
    except urllib.error.HTTPError:
        raise
    except (OSError, http.client.HTTPException) as error:
        deadline.remaining()
        raise urllib.error.URLError(error) from error
    finally:
        connection.close()
