"""Copy scr/_shared helpers into each function folder (Logos vendor-copy)."""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "scr" / "_shared"
MANIFEST = REPO / ".github" / "functions-paths.json"
YC_MDB_CA_URL = "https://storage.yandexcloud.net/cloud-certs/CA.pem"
SHARED_CERT = SHARED / "certs" / "root.crt"
FILES = (
    "common_log.py",
    "edge_http.py",
    "edge_pg.py",
    "edge_domain.py",
    "edge_intake.py",
    "edge_plane.py",
    "requirements.txt",
)

# Files a function folder must not keep after the move off YDB.
STALE = ("edge_ydb.py",)


def _cert_ready(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        text = path.read_text(encoding="ascii", errors="ignore")
    except OSError:
        return False
    return "BEGIN CERTIFICATE" in text


def _ensure_mdb_ca() -> bool:
    SHARED_CERT.parent.mkdir(parents=True, exist_ok=True)
    if _cert_ready(SHARED_CERT):
        return True
    tmp = SHARED_CERT.with_suffix(".crt.tmp")
    try:
        with urllib.request.urlopen(YC_MDB_CA_URL, timeout=30) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise urllib.error.URLError(f"HTTP {status}")
            body = resp.read()
        if not body or b"BEGIN CERTIFICATE" not in body:
            raise ValueError("response is not a PEM certificate")
        tmp.write_bytes(body)
        tmp.replace(SHARED_CERT)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        tmp.unlink(missing_ok=True)
        print(f"MDB CA download skipped ({exc}); {SHARED_CERT} not updated")
        return _cert_ready(SHARED_CERT)
    print(f"downloaded {SHARED_CERT}")
    return True


def main() -> None:
    have_cert = _ensure_mdb_ca()
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in entries:
        dest = REPO / entry["path"]
        dest.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            src = SHARED / name
            if src.exists():
                shutil.copy2(src, dest / name)
                print(f"copied {name} -> {dest}")
        if have_cert and _cert_ready(SHARED_CERT):
            cert_dir = dest / "certs"
            cert_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SHARED_CERT, cert_dir / "root.crt")
            print(f"copied certs/root.crt -> {dest}")
        else:
            print(f"skipped certs/root.crt -> {dest} (CA missing)")
        for name in STALE:
            leftover = dest / name
            if leftover.exists():
                leftover.unlink()
                print(f"removed stale {name} <- {dest}")


if __name__ == "__main__":
    main()
