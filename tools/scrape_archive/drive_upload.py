"""Optional Google Drive uploader.

Credentials come from the environment and are never written to disk by this
package:

- ``FML_DRIVE_ACCESS_TOKEN`` — a bearer token used as-is
- ``FML_DRIVE_REFRESH_TOKEN`` plus ``FML_DRIVE_CLIENT_ID`` and
  ``FML_DRIVE_CLIENT_SECRET`` — OAuth refresh
- ``FML_DRIVE_SERVICE_ACCOUNT_FILE`` or ``GOOGLE_APPLICATION_CREDENTIALS`` —
  a service-account JSON key. Share the destination folder with that
  account's ``client_email``. A service account has no storage of its own.
- ``FML_DRIVE_ROOT_FOLDER`` — parent folder id. The uploader finds or creates
  ``FML Scrape Archive`` inside it. Omit to use My Drive root.

Without credentials, ``upload`` refuses to run. ``upload_plan.json`` is the
handoff for an external agent that already has Drive access.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tools.scrape_archive.schema import DEFAULT_DRIVE_ROOT

_DRIVE = "https://www.googleapis.com/drive/v3/files"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_TOKEN = "https://oauth2.googleapis.com/token"
_FOLDER = "application/vnd.google-apps.folder"
_SCOPE = "https://www.googleapis.com/auth/drive"
_MIME = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


class DriveError(RuntimeError):
    pass


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise DriveError(f"token request failed ({exc.code}): {detail}") from exc


def _service_account_token(path: str) -> str:
    try:
        import jwt
    except ImportError as exc:
        raise DriveError("service-account upload needs PyJWT (import jwt)") from exc
    info = json.loads(Path(path).read_text(encoding="utf-8"))
    now = int(time.time())
    payload = {
        "iss": info["client_email"],
        "scope": _SCOPE,
        "aud": _TOKEN,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(payload, info["private_key"], algorithm="RS256")
    if isinstance(assertion, bytes):
        assertion = assertion.decode()
    body = _post_form(_TOKEN, {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    })
    token = body.get("access_token")
    if not token:
        raise DriveError("service-account token response had no access_token")
    return token


def access_token() -> str:
    """Resolve a Drive bearer token from the environment. Never logs it."""
    direct = os.environ.get("FML_DRIVE_ACCESS_TOKEN")
    if direct:
        return direct
    refresh = os.environ.get("FML_DRIVE_REFRESH_TOKEN")
    if refresh:
        client_id = os.environ.get("FML_DRIVE_CLIENT_ID")
        client_secret = os.environ.get("FML_DRIVE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise DriveError("FML_DRIVE_REFRESH_TOKEN requires FML_DRIVE_CLIENT_ID and FML_DRIVE_CLIENT_SECRET")
        body = _post_form(_TOKEN, {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        })
        token = body.get("access_token")
        if not token:
            raise DriveError("OAuth refresh response had no access_token")
        return token
    key_path = os.environ.get("FML_DRIVE_SERVICE_ACCOUNT_FILE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path:
        return _service_account_token(key_path)
    raise DriveError(
        "no Google Drive credentials. Set FML_DRIVE_ACCESS_TOKEN, or "
        "FML_DRIVE_REFRESH_TOKEN with FML_DRIVE_CLIENT_ID and FML_DRIVE_CLIENT_SECRET, or "
        "FML_DRIVE_SERVICE_ACCOUNT_FILE. Nothing was uploaded; use upload_plan.json."
    )


class DriveClient:
    def __init__(self, token: str):
        self.token = token
        self._folders: dict[tuple[str, str], str] = {}

    def _request(self, method: str, url: str, payload: bytes | None = None, content_type: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                return json.loads(raw.decode() or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise DriveError(f"Drive {method} {url.split('?', 1)[0]} failed ({exc.code}): {detail}") from exc

    def _list(self, query: str) -> list[dict]:
        files = []
        page = ""
        while True:
            params = {
                "q": query,
                "fields": "nextPageToken,files(id,name,md5Checksum,mimeType)",
                "pageSize": "100",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page:
                params["pageToken"] = page
            url = _DRIVE + "?" + urllib.parse.urlencode(params)
            body = self._request("GET", url)
            files.extend(body.get("files") or [])
            page = body.get("nextPageToken") or ""
            if not page:
                return files

    def folder(self, name: str, parent: str) -> str:
        cached = self._folders.get((parent, name))
        if cached:
            return cached
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"name = '{safe}' and mimeType = '{_FOLDER}' and "
            f"'{parent}' in parents and trashed = false"
        )
        found = self._list(query)
        if found:
            self._folders[(parent, name)] = found[0]["id"]
            return found[0]["id"]
        created = self._request(
            "POST",
            _DRIVE + "?supportsAllDrives=true",
            json.dumps({"name": name, "mimeType": _FOLDER, "parents": [parent]}).encode(),
            "application/json",
        )
        self._folders[(parent, name)] = created["id"]
        return created["id"]

    def ensure_path(self, drive_path: str, root_id: str) -> tuple[str, str]:
        parts = [part for part in drive_path.split("/") if part]
        if not parts:
            raise DriveError(f"empty drive path {drive_path!r}")
        parent = root_id
        for part in parts[:-1]:
            parent = self.folder(part, parent)
        return parent, parts[-1]

    def upload_file(self, local: Path, parent: str, name: str) -> str:
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"name = '{safe}' and '{parent}' in parents and trashed = false"
        existing = [item for item in self._list(query) if item.get("mimeType") != _FOLDER]
        mime = _MIME.get(local.suffix.lower(), "application/octet-stream")
        boundary = "fmlscrape" + hashlib_boundary()
        meta = json.dumps({"name": name, "parents": [parent]})
        file_bytes = local.read_bytes()
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
        ).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()
        content_type = f"multipart/related; boundary={boundary}"
        if existing:
            file_id = existing[0]["id"]
            url = f"{_UPLOAD}/{file_id}?uploadType=multipart&supportsAllDrives=true"
            self._request("PATCH", url, body, content_type)
            return file_id
        url = f"{_UPLOAD}?uploadType=multipart&supportsAllDrives=true"
        created = self._request("POST", url, body, content_type)
        return created.get("id", "")


def hashlib_boundary() -> str:
    return os.urandom(8).hex()


def upload(plan_path: str | Path, *, dry_run: bool = False, root_name: str | None = None) -> dict:
    """Create folders and upload every file in an ``upload_plan.json``."""
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    name = root_name or plan.get("root_folder_name") or DEFAULT_DRIVE_ROOT
    files = plan.get("files") or []
    if dry_run:
        return {"dry_run": True, "root_folder_name": name, "file_count": len(files), "uploaded": 0}
    token = access_token()
    client = DriveClient(token)
    parent = os.environ.get("FML_DRIVE_ROOT_FOLDER") or "root"
    root_id = client.folder(name, parent)
    uploaded = 0
    for item in files:
        local = Path(item["local_path"])
        if not local.is_file():
            raise DriveError(f"missing local file {local}")
        folder_id, filename = client.ensure_path(item["drive_path"], root_id)
        client.upload_file(local, folder_id, filename)
        uploaded += 1
    return {"dry_run": False, "root_folder_name": name, "root_folder_id": root_id, "uploaded": uploaded}
