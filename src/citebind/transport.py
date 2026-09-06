"""The transport seam: how resolvers talk to Crossref and PubMed.

Architecture (decided by the driver, review note 2026-08-31): one small
transport interface, two implementations. ``HttpTransport`` speaks real
HTTP for production and for the deliberate, separate act of recording
fixtures. ``ReplayTransport`` reads archived raw responses from disk and is
what every test uses — there is no network anywhere in the suite, and the
seam itself is the enforcement (no socket mocking).

Response-level refusals are named and distinct (``ResponseError``):
``http_error`` for 4xx/5xx statuses, ``malformed_json`` for bodies that do
not parse, ``empty_result`` for empty result sets. Transport-level
refusals are named and distinct (``TransportError``): ``timeout``,
``connection_error``, ``url_not_recorded`` (replay only — a test asking
for a URL nobody recorded is a test bug and must be loud).
"""

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CODE_TIMEOUT = "timeout"
CODE_CONNECTION_ERROR = "connection_error"
CODE_URL_NOT_RECORDED = "url_not_recorded"
CODE_HTTP_ERROR = "http_error"
CODE_MALFORMED_JSON = "malformed_json"
CODE_EMPTY_RESULT = "empty_result"


class TransportError(Exception):
    """Fetching over a transport failed, with a named reason."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


class ResponseError(Exception):
    """A fetched response was refused, with a named reason."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


@dataclass(frozen=True)
class TransportResponse:
    """Raw response: HTTP status and unmodified body bytes."""

    status: int
    body: bytes


class Transport(Protocol):
    def fetch(self, url: str) -> TransportResponse: ...


def classify_urlopen_error(error: Exception) -> TransportError:
    """Map a urllib error to its named transport error. Pure; no network.

    Separated from HttpTransport.fetch so the classification is testable
    without opening a socket: the HTTP path itself is deliberately thin and
    untested in CI — the replay twin is what the suite exercises.
    """
    if isinstance(error, (TimeoutError, socket.timeout)):
        return TransportError(CODE_TIMEOUT, f"request timed out: {error}")
    if isinstance(error, urllib.error.URLError):
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            return TransportError(CODE_TIMEOUT, f"request timed out: {error.reason}")
        return TransportError(
            CODE_CONNECTION_ERROR, f"could not connect: {error.reason}"
        )
    if isinstance(error, OSError):
        return TransportError(CODE_CONNECTION_ERROR, f"could not connect: {error}")
    return TransportError(CODE_CONNECTION_ERROR, f"request failed: {error}")


# FIXME(driver): the mailto is a PLACEHOLDER. Crossref routes polite-pool
# traffic on a reachable contact address; the real one is the user's to
# give. Flagged for the driver rather than invented (review note N1).
#
# ORDERING: fix this BEFORE the N3 re-record. The 2026-09-01 fixtures
# already went out to Crossref and NCBI under a placeholder address
# (`CiteBind-recording/0.1 (mailto:example@example.org)`); re-recording
# while this line still reads example@example.org repeats that, and this
# time stamps the fake contact into the manifest as provenance.
USER_AGENT = (
    "CiteBind/0.1 (https://github.com/tengzhang48/CiteBind; "
    "mailto:example@example.org)"
)


class HttpTransport:
    """Real HTTP via urllib, with a timeout. Used in production and by the
    recording script; never used by tests, which run on ReplayTransport.

    The fixtures currently in spike/recordings/ did NOT come from this
    class. They were recorded 2026-09-01 at T-12 by the recorder's own
    urlopen under a `CiteBind-recording/0.1` User-Agent, one day before the
    N1 consolidation put the recorder on this transport. Re-recording makes
    the shared-path claim true by construction (review note N3); until it
    happens, this is the path production uses and those files are artifacts
    of a path that no longer exists."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def fetch(self, url: str) -> TransportResponse:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return TransportResponse(
                    status=response.status, body=response.read()
                )
        except urllib.error.HTTPError as error:
            # 4xx/5xx are responses, not transport failures: the status is
            # preserved so the resolver layer refuses it by name.
            return TransportResponse(status=error.code, body=error.read())
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as error:
            raise classify_urlopen_error(error) from error


class ReplayTransport:
    """Replay recorded raw responses from disk, via a manifest mapping URLs
    to files. The only transport the test suite uses."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = Path(manifest_path)
        self._by_url: dict[str, dict] = {}
        try:
            data = json.loads(self.manifest_path.read_text())
        except json.JSONDecodeError as error:
            raise TransportError(
                "malformed_manifest",
                f"{self.manifest_path} is not valid JSON: {error}",
            ) from error
        for recording in data.get("recordings", []):
            self._by_url[recording["url"]] = recording

    def fetch(self, url: str) -> TransportResponse:
        recording = self._by_url.get(url)
        if recording is None:
            raise TransportError(
                CODE_URL_NOT_RECORDED,
                f"'{url}' has no recording in {self.manifest_path}; "
                "a test asked for a URL nobody recorded",
            )
        body = (self.manifest_path.parent / recording["file"]).read_bytes()
        return TransportResponse(status=recording.get("status", 200), body=body)


def check_status(response: TransportResponse, source: str) -> None:
    """Refuse HTTP error statuses by name (``http_error``)."""
    if response.status >= 400:
        raise ResponseError(
            CODE_HTTP_ERROR,
            f"HTTP {response.status} from {source}",
        )


def decode_json(response: TransportResponse, source: str):
    """Parse a response body as JSON, refusing by name (``malformed_json``)."""
    try:
        return json.loads(response.body)
    except json.JSONDecodeError as error:
        raise ResponseError(
            CODE_MALFORMED_JSON,
            f"response from {source} is not valid JSON: {error}",
        ) from error


def require_non_empty(items, source: str, what: str) -> None:
    """Refuse an empty result set by name (``empty_result``)."""
    if not items:
        raise ResponseError(
            CODE_EMPTY_RESULT,
            f"{what} returned no results from {source}",
        )

