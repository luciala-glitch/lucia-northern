"""Rebuild the figures, tables and report for the saved 15-tooth study."""
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from week3.analyze import group_pairs, statistics_report, synthetic_cases, write_csv
from week3.comparison import compare_conditions
from week3.errors import decompose_displacements
from week3.exports import csv_export, csv_import, json_export, landmarks_from_record, validate_record
from week3.image_processing import crest_profile, preprocess
from week3.pbl_calculator import calculate_tooth_pbl
from week3.sensitivity import sensitivity
from week3.reports.collected_study.paired_analysis import paired_statistics, plot_case
from week3.reports.collected_study.radiographic_cases import build_cases
from week3.reports.collected_study.verification import verify_evidence

ROOT=Path('week3/reports/collected_study')
CONDITIONS=('raw','he','clahe')
INPUT_SHA='4e9f6cac5410a14ded62961f383377861d0b8f03abaaa72859a30c45a2a3daa8'


def load_data():
    source=ROOT/'exports/measurements.json'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=INPUT_SHA:
        raise ValueError('This report is frozen to the audited 90-reading dataset; review the text before changing input.')
    data=json.loads(source.read_text())
    for r in data:validate_record(r)
    identities=[(r['tooth_id'],r['condition'],r['round']) for r in data]
    expected={(t,c,r) for t in range(1,16) for c in CONDITIONS for r in (1,2)}
    assert len(identities)==len(set(identities))==90 and set(identities)==expected
    assert {r['image_id'] for r in data}=={'kaggle_dental_xray_1.jpg'}
    assert json.loads(json_export(data))==data
    assert csv_import(csv_export(data))==data
    assert csv_import((ROOT/'exports/measurements.csv').read_text())==data
    image=Path('week2/sample_xrays/kaggle_dental_xray_1.jpg')
    manifest=json.loads((ROOT/'exports/collection_manifest.json').read_text())
    assert hashlib.sha256(image.read_bytes()).hexdigest()==manifest['image_sha256'][image.name]
    with Image.open(image) as im:
        for r in data:
            lm=r['landmarks']
            points=[lm['apex']]+[lm[s][k] for s in ('mesial','distal') for k in ('cej','bc')]
            assert all(0<=x<im.width and 0<=y<im.height for x,y in points)
    return data


def build_base(data):
    lookup={(r['tooth_id'],r['condition'],r['round']):r for r in data}
    comparison=compare_conditions(data)
    (ROOT/'preprocessing_comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
    stats={};ranked={};trials=[];decomposition=[]
    for c in CONDITIONS:
        records=[dict(key=('study',r['image_id'],r['tooth_id']),round=r['round'],landmarks=landmarks_from_record(r),result=calculate_tooth_pbl(landmarks_from_record(r))) for r in data if r['condition']==c]
        pairs=group_pairs(records);target=ROOT/c;target.mkdir(exist_ok=True)
        summary,_,_=statistics_report(pairs,target,c)
        stats[c]=json.loads((target/'statistics.json').read_text())
        errors=decompose_displacements([(a['landmarks'],b['landmarks']) for a,b in pairs])
        write_csv(target/'error_decomposition.csv',errors)
        decomposition.extend(dict(condition=c,**r) for r in errors)
        for a,b in pairs:
            t=a['key'][-1]
            delta=[getattr(b['result'],s).pbl_pct-getattr(a['result'],s).pbl_pct for s in ('mesial','distal')]
            score=max(abs(v-summary.bias) for v in delta)
            if t not in ranked or score>ranked[t]['score']:
                ranked[t]=dict(tooth=t,condition=c,score=score,mesial_pp=delta[0],distal_pp=delta[1])
            trials.extend(dict(condition=c,tooth_id=t,**r) for r in sensitivity(a['landmarks']))
    cases=sorted(ranked.values(),key=lambda r:r['score'],reverse=True)[:5]
    write_csv(ROOT/'worst_cases.csv',cases);write_csv(ROOT/'sensitivity.csv',trials)
    summary=[]
    for size in (2,5,10):
        for direction in ('parallel','normal'):
            rows=[r for r in trials if abs(r['shift_px'])==size and r['direction']==direction]
            valid=[abs(r['max_change_pp']) for r in rows if r['status']=='valid']
            summary.append(dict(shift_px=size,direction=direction,trials=len(rows),rejected=sum(r['status']!='valid' for r in rows),mean_abs_change_pp=float(np.mean(valid)) if valid else None,max_abs_change_pp=max(valid) if valid else None,stage_changes=sum(r.get('stage_changed') is True for r in rows)))
    write_csv(ROOT/'sensitivity_summary.csv',summary)
    selected=[]
    for rank,case in enumerate(cases,1):
        selected.extend(dict(rank=rank,**r) for r in trials if r['tooth_id']==case['tooth'] and r['condition']==case['condition'] and abs(r['shift_px']) in (5,10))
        plot_case(ROOT,data,case['tooth'],case['condition'],f'case_{rank}.png',f'Review rank {rank}')
    assert len(selected)==200
    write_csv(ROOT/'case_sensitivity.csv',selected)
    plot_case(ROOT,data,7,'he','he_t7_flag.png','Additional flagged condition')
    synthetic_cases(ROOT)
    return lookup,stats,comparison,cases,summary,selected,decomposition


def build_paired(data):
    result=paired_statistics(data)
    (ROOT/'supplementary_statistics.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    confusion=[]
    for c,v in result['conditions'].items():
        for i,stage in enumerate(('I','II','III/IV')):
            counts=v['tooth_confusion'][i]
            confusion.append(dict(condition=c,round1_stage=stage,round2_I=counts[0],round2_II=counts[1],round2_III_IV=counts[2]))
        y=np.array([v['tooth_round1'],v['tooth_round2']]).T
        fig,ax=plt.subplots(figsize=(8,4.8),layout='constrained');ax.scatter(y.mean(1),y[:,1]-y[:,0])
        for value,label in [(v['tooth_bias'],'Bias'),(v['tooth_loa_lower'],'Lower LoA'),(v['tooth_loa_upper'],'Upper LoA')]:
            ax.axhline(value,ls='--',label=f'{label}: {value:.3f} pp')
        ax.set(xlabel='Mean tooth PBLmax (%)',ylabel='R2 − R1 (pp)',title=f'{c.upper()} tooth-level Bland–Altman: 15 teeth');ax.legend();ax.grid(alpha=.15)
        fig.savefig(ROOT/c/'tooth_bland_altman.png',dpi=160);plt.close(fig)
    write_csv(ROOT/'tooth_stage_confusion.csv',confusion)
    return result


def build_edges(lookup):
    image=Image.open('week2/sample_xrays/kaggle_dental_xray_1.jpg');rows=[];profiles={}
    for c in CONDITIONS:
        enhanced=preprocess(image,c)
        for t in range(1,16):
            lm=landmarks_from_record(lookup[t,'raw',1]);tangent=tuple(float(d-m) for d,m in zip(lm.distal.bc,lm.mesial.bc))
            for side in ('mesial','distal'):
                off,intensity,gradient=crest_profile(enhanced,getattr(lm,side).bc,tangent)
                peak=float(off[np.argmax(gradient)]);local=abs(off)<=3
                rows.append(dict(condition=c,tooth_id=t,side=side,full_peak_offset_px=peak,full_peak_gradient=float(gradient.max()),local3_peak_gradient=float(gradient[local].max()),full_peak_abs_offset_ge8=abs(peak)>=8,full_peak_at_boundary=abs(peak)==10))
                if t==1 and side=='mesial':profiles[c]=(off,intensity,gradient)
    write_csv(ROOT/'crest_gradient_diagnostics.csv',rows)
    write_csv(ROOT/'crest_edge_metrics.csv',[dict(condition=r['condition'],tooth_id=r['tooth_id'],side=r['side'],peak_gradient=r['full_peak_gradient'],peak_offset=r['full_peak_offset_px']) for r in rows])
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
    for c,(off,intensity,gradient) in profiles.items():
        axes[0].plot(off,intensity,label=c.upper());axes[1].plot(off,gradient,label=c.upper())
    for ax in axes:ax.set_xlabel('Offset from fixed RAW R1 crest (px)');ax.legend();ax.grid(alpha=.15)
    axes[0].set_ylabel('Intensity (8-bit gray)');axes[1].set_ylabel('|dI/ds| (gray levels/px)')
    fig.suptitle('T1 mesial crest: fixed-location contrast comparison');fig.savefig(ROOT/'crest_profile.png',dpi=160);plt.close(fig)
    return rows


def markdown_table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    verification=verify_evidence(ROOT)
    data=load_data()
    lookup,stats,comparison,cases,sensitivity_summary,selected,decomposition=build_base(data)
    paired=build_paired(data);edges=build_edges(lookup);build_cases(ROOT)
    counts=verification['counts'];coverage=json.loads((ROOT/'full_coverage.json').read_text())['files']['week3/pbl_calculator.py']['summary']
    values={}
    values['agreement']=markdown_table(['Condition','Surface ICC(2,1)','Surface weighted κ','Tooth weighted κ','Bias (pp)','95% LoA (pp)'],[[c.upper(),f"{stats[c]['icc_2_1']:.3f}",f"{stats[c]['weighted_kappa']:.3f}",f"{stats[c]['tooth_stage_quadratic_kappa']:.3f}",f"{stats[c]['bias']:+.3f}",f"{stats[c]['loa_lower']:.3f} to {stats[c]['loa_upper']:.3f}"] for c in CONDITIONS])
    values['tooth']=markdown_table(['Condition','PBLmax ICC','Tooth bias (pp)','Tooth 95% LoA (pp)','Clustered surface ICC 95% interval'],[[c.upper(),f"{paired['conditions'][c]['tooth_icc']:.3f}",f"{paired['conditions'][c]['tooth_bias']:+.3f}",f"{paired['conditions'][c]['tooth_loa_lower']:.3f} to {paired['conditions'][c]['tooth_loa_upper']:.3f}",' to '.join(f'{v:.3f}' for v in paired['conditions'][c]['clustered_surface_icc_ci'])] for c in CONDITIONS])
    values['bias_intervals']='; '.join(c.upper()+' '+ ' to '.join(f'{v:.2f}' for v in paired['conditions'][c]['clustered_bias_ci'])+' pp' for c in CONDITIONS)
    values['confusion']=markdown_table(['Condition','II → II','II → III/IV','III/IV → II','III/IV → III/IV','Disagreements / 15'],[[c.upper(),*[paired['conditions'][c]['tooth_confusion'][a][b] for a,b in [(1,1),(1,2),(2,1),(2,2)]],paired['conditions'][c]['tooth_stage_mismatches']] for c in CONDITIONS])
    values['contrast']=markdown_table(['Condition','Coordinate RMSD vs Raw (px)','Round-to-round RMSD (px)','Coordinate variance (px²)'],[[c.upper(),'Reference' if c=='raw' else f"{comparison['conditions'][c]['coordinate_rmsd_vs_raw_px']:.3f}",f"{comparison['conditions'][c]['round_coordinate_rmsd_px']:.3f}",f"{comparison['conditions'][c]['mean_within_landmark_coordinate_variance_px2']:.3f}"] for c in CONDITIONS])
    values['displacement']=markdown_table(['Condition','Landmark','Mean drift (px)','Centered residual RMS (px)'],[[r['condition'].upper(),r['landmark'],f"{r['mean_drift_magnitude_px']:.3f}",f"{r['centered_residual_rms_px']:.3f}"] for r in decomposition])
    values['sensitivity']=markdown_table(['Shift (px)','Direction','Mean absolute ΔPBLmax (pp)','Maximum absolute ΔPBLmax (pp)','Rejected / trials'],[[r['shift_px'],r['direction'],f"{r['mean_abs_change_pp']:.3f}",f"{r['max_abs_change_pp']:.3f}",f"{r['rejected']} / {r['trials']}"] for r in sensitivity_summary])
    case_table=[]
    for case in cases:
        row=[f"T{case['tooth']}",case['condition'].upper()]
        for shift in (-10,-5,5,10):
            trials=[r for r in selected if r['tooth_id']==case['tooth'] and r['condition']==case['condition'] and r['shift_px']==shift and r['direction']=='parallel' and r['status']=='valid']
            row.append(f"{max(abs(r['max_change_pp']) for r in trials):.3f}" if trials else 'N/A')
        case_table.append(row)
    values['case_sensitivity']=markdown_table(['Tooth','Condition','−10 px','−5 px','+5 px','+10 px'],case_table)
    values['case_figures']='\n\n'.join(f"![T{case['tooth']} {case['condition'].upper()}](case_{rank}.png)" for rank,case in enumerate(cases,1))
    flags=[]
    for c in CONDITIONS:
        with (ROOT/c/'surface_agreement.csv').open() as f:
            flags.extend(f"{c.upper()} T{r['identity']} ({float(r['difference_pp']):+.2f} pp)" for r in csv.DictReader(f) if r['outside_loa']=='True')
    values['flags']='; '.join(flags)+'.'
    values['edges']=markdown_table(['Condition','Mean full-window peak (gray/px)','Mean ±3 px peak (gray/px)','Full peak at ≥8 px / 30'],[[c.upper(),f"{np.mean([r['full_peak_gradient'] for r in edges if r['condition']==c]):.3f}",f"{np.mean([r['local3_peak_gradient'] for r in edges if r['condition']==c]):.3f}",sum(r['full_peak_abs_offset_ge8'] for r in edges if r['condition']==c)] for c in CONDITIONS])
    values['test_summary']=f"The checks dated {verification['checked_local_date']} passed {counts['week3']} Week 3 Python tests, {counts['project']} project Python tests and {counts['frontend']} frontend tests. The PBL engine covered {coverage['covered_branches']}/{coverage['num_branches']} branches ({100*coverage['covered_branches']/coverage['num_branches']:.0f}%)."
    template=(ROOT/'report_template.md').read_text()
    for key,value in values.items():template=template.replace('{{'+key+'}}',value)
    assert '{{' not in template
    (ROOT/'WEEK3_COLLECTED_REPORT.md').write_text(template)
    print('Generated report and figures: 90 readings, 2700 perturbation trials, five ranked cases.')


if __name__=='__main__':main()
