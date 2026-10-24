"""Run current checks and bind their saved evidence to source-file hashes."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path('week3/reports/collected_study')


def hashes(paths):
    return {p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def source_files():
    return [*Path('week3').glob('*.py'),*Path('week3/tests').glob('*.py'),*ROOT.glob('*.py'),ROOT/'report_template.md']


def record_evidence(checked_utc, source_before=None):
    sources=hashes(source_files())
    if source_before is not None and sources!=source_before:
        raise RuntimeError('Source files changed while checks were running; run again.')
    logs={k:(ROOT/f'{name}_test_results.txt').read_text() for k,name in [('week3','week3'),('project','project'),('frontend','frontend')]}
    counts={k:int(re.search(r'(\d+) passed',logs[k]).group(1)) for k in ('week3','project')}
    counts['frontend']=int(re.search(r'pass (\d+)',logs['frontend']).group(1))
    if 'fail 0' not in logs['frontend'] or any(re.search(r'\d+ failed',logs[k]) for k in ('week3','project')):
        raise RuntimeError('Cannot record failing checks.')
    coverage=json.loads((ROOT/'full_coverage.json').read_text())
    engine=coverage['files']['week3/pbl_calculator.py']['summary']
    if engine['missing_branches'] or not engine['num_branches']:
        raise RuntimeError('Expected complete engine branch coverage.')
    artifacts=[ROOT/f'{k}_test_results.txt' for k in ('week3','project','frontend')]
    artifacts += [ROOT/'full_coverage.json',*list((ROOT/'protocol_history').glob('*.json'))]
    evidence=dict(checked_utc=checked_utc,
        timezone='America/Detroit',counts=counts,source_digests=sources,
        artifact_digests=hashes(artifacts),
        note='Saved execution evidence; report generation verifies hashes but does not execute tests. Clinical accuracy is not inferred from software checks.')
    # The date is derived from the recorded run, rather than report generation.
    from zoneinfo import ZoneInfo
    evidence['checked_local_date']=datetime.fromisoformat(checked_utc.replace('Z','+00:00')).astimezone(ZoneInfo(evidence['timezone'])).date().isoformat()
    (ROOT/'verification_manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--node',default='node');args=parser.parse_args()
    node=shutil.which(args.node)
    if not node: raise SystemExit('Node was not found; pass --node /path/to/node.')
    before=hashes(source_files())
    commands=[('week3',[sys.executable,'-m','pytest','week3/tests','--cov=week3','--cov-branch','--cov-report=term-missing',f'--cov-report=json:{ROOT}/full_coverage.json','-q']),('project',[sys.executable,'-m','pytest','-q']),('frontend',[node,'--test','week3/tests/canvas_frontend.test.cjs'])]
    for name,command in commands:
        print(f'Running {name} checks...',flush=True)
        with (ROOT/f'{name}_test_results.txt').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    evidence=record_evidence(datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),before)
    print('Saved passing checks:',evidence['counts'])


if __name__=='__main__': main()
