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
CODE_RECORDING_FILE_MISSING = "recording_file_missing"
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


# Identify the project without claiming a contact address nobody supplied.
USER_AGENT = "CiteBind/0.1.0 (https://github.com/tengzhang48/CiteBind)"


class HttpTransport:
    """Real HTTP via urllib, with a timeout. Used in production and by the
    recording script; never used by tests, which run on ReplayTransport.

    Historical recordings predate this shared transport and lack complete
    retrieval provenance. New recordings use this class and record the actual
    User-Agent and retrieval time; public fixtures omit publisher abstracts.
    See spike/recordings/README.md.
    """

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
    to files. The only transport the test suite uses.

    TRUST BOUNDARY: a manifest is authored fixture content committed to this
    repository, not input from a document or a user, so ``file`` is joined to
    the manifest's directory without containment checks and an absolute path
    is honoured (test_crossref points one at an archived response elsewhere in
    the tree). If manifests ever arrive from outside -- a downloaded recording
    bundle, a fixture set shared between projects -- that assumption ends and
    this join needs to refuse paths that escape the manifest's directory."""

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
        path = self.manifest_path.parent / recording["file"]
        try:
            body = path.read_bytes()
        except OSError as error:
            # A manifest entry naming a file that is not there: named, like
            # every other failure in this module, instead of surfacing a bare
            # FileNotFoundError from three frames down. The manifest and the
            # recordings are one artifact, and this says which half is missing.
            raise TransportError(
                CODE_RECORDING_FILE_MISSING,
                f"'{url}' is listed in {self.manifest_path} as "
                f"{recording['file']!r}, but that file could not be read: {error}",
            ) from error
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
