"""Record or check SHA-256 digests of the released fold checkpoints.

Retraining on another machine (or on MPS vs CUDA) is not bit-identical, so a
mismatch after retraining is reported, not treated as an error, unless
``--strict`` is given (use it after downloading the released weights).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

WEIGHTS = Path(__file__).resolve().parent / "weights"
MANIFEST = WEIGHTS / "MANIFEST.json"
EXPECTED = [f"{c}_fold_{f}.pt" for c in ("raw", "clahe") for f in range(1, 6)]


def digests() -> dict[str, str]:
    return {
        name: hashlib.sha256((WEIGHTS / name).read_bytes()).hexdigest()
        for name in EXPECTED
        if (WEIGHTS / name).is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    current = digests()
    if not args.check:
        MANIFEST.write_text(json.dumps(current, indent=2) + "\n")
        print(f"Wrote {len(current)} digests to {MANIFEST}")
        return
    expected = json.loads(MANIFEST.read_text()) if MANIFEST.is_file() else {}
    missing = [name for name in EXPECTED if name not in current]
    changed = [name for name, value in current.items() if expected.get(name) != value]
    if missing:
        raise SystemExit(f"Missing checkpoints: {', '.join(missing)}")
    if changed:
        message = f"{len(changed)} checkpoint(s) differ from the released MANIFEST (retrained?): {', '.join(changed)}"
        if args.strict:
            raise SystemExit(message)
        print("WARNING: " + message)
    else:
        print("All 10 checkpoints match the released MANIFEST.")


if __name__ == "__main__":
    main()
