"""Download and verify the DenPAR v3 archive (CC BY 4.0, 141 MB) into week4/data."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

URL = "https://zenodo.org/api/records/16645076/files/DenPAR%20Radiographs%20Dataset.zip/content"
SHA256 = "b9edb55020f2cb971ba771b4cf5e4b65c4abb4df957310bd2eccc83d5a08b072"
TARGET = Path(__file__).resolve().parent / "data" / "denpar_full"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if (TARGET / "Training" / "Images").is_dir():
        print(f"DenPAR already present at {TARGET}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "denpar.zip"
        print("Downloading DenPAR v3 from Zenodo (141 MB)...")
        urllib.request.urlretrieve(URL, archive)
        if sha256(archive) != SHA256:
            raise SystemExit("DenPAR checksum mismatch; refusing to use the download")
        extracted = Path(tmp) / "extracted"
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                resolved = (extracted / member).resolve()
                if not resolved.is_relative_to(extracted.resolve()):
                    raise SystemExit(f"Unsafe path in archive: {member}")
            bundle.extractall(extracted)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted / "Dataset"), TARGET)
    print(f"DenPAR extracted to {TARGET}")


if __name__ == "__main__":
    main()
