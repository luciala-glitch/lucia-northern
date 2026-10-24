"""Verify saved test evidence; regenerating a report does not rerun tests."""
import hashlib
import json
from pathlib import Path


def verify_evidence(root):
    evidence=json.loads((Path(root)/'verification_manifest.json').read_text())
    for group in ('source_digests','artifact_digests'):
        for name,expected in evidence[group].items():
            path=Path(name)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise ValueError(f'Saved test/provenance evidence is stale: {name}. Rerun checks and refresh the verification manifest.')
    return evidence
