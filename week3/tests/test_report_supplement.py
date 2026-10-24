"""Check the additional paired analyses and the synthetic figure explanation."""
import json
from pathlib import Path
import numpy as np
import pytest
import matplotlib.axes
from week3.analyze import synthetic_cases
from week3.reports.collected_study.paired_analysis import batch_icc, paired_statistics


def test_batch_icc_hand_derived_and_undefined():
    values=np.array([[[1,2],[2,4],[3,6]],[[1,1],[2,2],[3,3]]])
    assert batch_icc(values)==pytest.approx([6/13,1])
    assert np.isnan(batch_icc(np.ones((3,2))))


def test_tooth_level_reference_and_cluster_unit():
    data=json.loads(Path('week3/reports/collected_study/exports/measurements.json').read_text())
    result=paired_statistics(data,repeats=200,seed=16)
    assert [result['conditions'][c]['tooth_icc'] for c in ('raw','he','clahe')]==pytest.approx([.689,.742,.792],abs=.0006)
    assert [result['conditions'][c]['tooth_stage_mismatches'] for c in ('raw','he','clahe')]==[4,1,3]
    # Direct tooth-mean differences verify that each bootstrap bias draw keeps
    # both surfaces paired, rather than drawing 30 unrelated surfaces.
    lookup={(r['tooth_id'],r['condition'],r['round']):r for r in data}
    tooth_mean_delta=np.array([np.mean([lookup[t,'raw',2]['metrics'][s+'_pbl_pct']-lookup[t,'raw',1]['metrics'][s+'_pbl_pct'] for s in ('mesial','distal')]) for t in range(1,16)])
    draws=np.random.default_rng(16).integers(0,15,size=(200,15))
    expected=np.quantile(tooth_mean_delta[draws].mean(1),[.025,.975])
    assert result['conditions']['raw']['clustered_bias_ci']==pytest.approx(expected)
    assert result['conditions']['raw']['bootstrap_finite']==200


def test_synthetic_cej_title_explains_affected_side(monkeypatch,tmp_path):
    titles=[]
    original=matplotlib.axes.Axes.set_title
    def capture(self,label,*args,**kwargs):
        titles.append(label)
        return original(self,label,*args,**kwargs)
    monkeypatch.setattr(matplotlib.axes.Axes,'set_title',capture)
    synthetic_cases(tmp_path)
    first=next(s for s in titles if s.startswith('Obscured CEJ'))
    assert 'Mesial Δ: -' in first
    assert 'worse-side Δ: +0.00 pp' in first
    assert (tmp_path/'synthetic_failure_cases.png').is_file()


@pytest.mark.parametrize('changed_group',['source_digests','artifact_digests'])
def test_verification_fails_on_stale_source_or_logs(tmp_path,changed_group):
    import hashlib
    from week3.reports.collected_study.verification import verify_evidence
    evidence={}
    for group in ('source_digests','artifact_digests'):
        p=tmp_path/group;p.write_text('audited')
        evidence[group]={str(p):hashlib.sha256(p.read_bytes()).hexdigest()}
    (tmp_path/'verification_manifest.json').write_text(json.dumps(evidence))
    assert verify_evidence(tmp_path)==evidence
    (tmp_path/changed_group).write_text('changed')
    with pytest.raises(ValueError,match='evidence is stale'):
        verify_evidence(tmp_path)
