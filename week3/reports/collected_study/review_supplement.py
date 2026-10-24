"""Additional, tooth-paired analyses for the frozen collected-study report.

The archived RAW session is provenance only and never enters these statistics.
"""
from datetime import datetime
import csv
import json
from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
from week3.analyze import write_csv
from week3.exports import landmarks_from_record
from week3.image_processing import preprocess, crest_profile
from week3.pbl_calculator import calculate_tooth_pbl, stage_pbl
from week3.statistics import agreement

CONDITIONS = ('raw', 'he', 'clahe')
STAGES = ('I', 'II', 'III/IV')


def batch_icc(y):
    """Absolute-agreement single-measure ICC for (..., subjects, rounds)."""
    y = np.asarray(y, dtype=float)
    n, k = y.shape[-2:]
    grand = y.mean(axis=(-2, -1), keepdims=True)
    subjects = y.mean(axis=-1, keepdims=True)
    rounds = y.mean(axis=-2, keepdims=True)
    ms_subject = k * np.square(subjects - grand).sum(axis=(-2, -1)) / (n - 1)
    ms_round = n * np.square(rounds - grand).sum(axis=(-2, -1)) / (k - 1)
    ms_error = np.square(y - subjects - rounds + grand).sum(axis=(-2, -1)) / ((n - 1) * (k - 1))
    denominator = ms_subject + (k - 1) * ms_error + k * (ms_round - ms_error) / n
    return np.divide(ms_subject - ms_error, denominator,
                     out=np.full_like(denominator, np.nan), where=denominator != 0)


def paired_statistics(data, repeats=10000, seed=20261023):
    """Resample whole teeth, retaining both surfaces and both rounds together."""
    lookup = {(r['tooth_id'], r['condition'], r['round']): r for r in data}
    draws = np.random.default_rng(seed).integers(0, 15, size=(repeats, 15))
    result = {}
    for c in CONDITIONS:
        y = np.array([[[lookup[t,c,r]['metrics'][s+'_pbl_pct'] for r in (1,2)]
                       for s in ('mesial','distal')] for t in range(1,16)])
        tooth = y.max(axis=1)
        summary = agreement(tooth[:,0], tooth[:,1],
                            [STAGES.index(stage_pbl(v)) for v in tooth[:,0]],
                            [STAGES.index(stage_pbl(v)) for v in tooth[:,1]])
        sampled = y[draws].reshape(repeats,30,2)
        boot_icc = batch_icc(sampled)
        bias = (sampled[:,:,1] - sampled[:,:,0]).mean(axis=1)
        difference = y[:,:,1] - y[:,:,0]
        confusion = np.zeros((3,3), dtype=int)
        for a,b in tooth:
            confusion[STAGES.index(stage_pbl(a)),STAGES.index(stage_pbl(b))] += 1
        result[c] = dict(
            tooth_icc=float(batch_icc(tooth)), tooth_bias=summary.bias,
            tooth_sd=summary.difference_sd, tooth_loa_lower=summary.loa_lower,
            tooth_loa_upper=summary.loa_upper,
            clustered_surface_icc_ci=np.quantile(boot_icc[np.isfinite(boot_icc)], [.025,.975]).tolist(),
            clustered_bias_ci=np.quantile(bias,[.025,.975]).tolist(),
            bootstrap_finite=int(np.isfinite(boot_icc).sum()),
            difference_correlation=float(np.corrcoef(difference.T)[0,1]),
            tooth_confusion=confusion.tolist(),
            tooth_stage_mismatches=int(confusion.sum()-np.trace(confusion)),
            tooth_round1=tooth[:,0].tolist(), tooth_round2=tooth[:,1].tolist())
    return dict(repeats=repeats, seed=seed, conditions=result)


def plot_case(root, data, tooth, condition, filename, label):
    lookup = {(r['tooth_id'],r['condition'],r['round']):r for r in data}
    first,second = (lookup[tooth,condition,r] for r in (1,2))
    a,b = landmarks_from_record(first),landmarks_from_record(second)
    fig,ax = plt.subplots(figsize=(6.7,6.5),layout='constrained')
    image = Image.open('week2/sample_xrays/kaggle_dental_xray_1.jpg')
    ax.imshow(preprocess(image,condition),cmap='gray',vmin=0,vmax=255)
    points = []
    for name in ('mesial.cej','mesial.bc','distal.cej','distal.bc','apex'):
        def get(lm):
            if name=='apex': return np.array(lm.apex)
            side,key=name.split('.'); return np.array(getattr(getattr(lm,side),key))
        p,q=get(a),get(b);points.extend([p,q])
        ax.scatter(*p,c='#00d5ff',s=20);ax.scatter(*q,c='#ffae36',s=20)
        ax.annotate('',xy=q,xytext=p,arrowprops={'arrowstyle':'->','color':'#ffae36'})
        ax.annotate(name,p,xytext=(4,5),textcoords='offset points',color='#00d5ff',fontsize=8)
    u=np.array(first['long_axis_vector'])
    ax.plot([a.mid_cej[0],a.apex[0]],[a.mid_cej[1],a.apex[1]],color='#79ff79',label='R1 axis')
    for side in (a.mesial,a.distal):
        p=np.array(side.cej);bc=np.array(side.bc);projection=p+np.dot(bc-p,u)*u
        ax.plot([p[0],projection[0]],[p[1],projection[1]],color='#ff70b7')
        ax.plot([bc[0],projection[0]],[bc[1],projection[1]],'--',color='#ff70b7')
    pts=np.array(points);ax.set_xlim(pts[:,0].min()-60,pts[:,0].max()+60)
    ax.set_ylim(pts[:,1].max()+45,pts[:,1].min()-45)
    x,y=first['metrics'],second['metrics']
    ax.set_title(f'{label}: T{tooth}, {condition.upper()}\n'
                 f'R1 M {x["mesial_pbl_pct"]:.2f}% / D {x["distal_pbl_pct"]:.2f}%\n'
                 f'R2 M {y["mesial_pbl_pct"]:.2f}% / D {y["distal_pbl_pct"]:.2f}%\n'
                 'Cyan R1 / orange R2; manually annotated shared apex', fontsize=10)
    ax.legend();fig.savefig(root/filename,dpi=150);plt.close(fig)


def amend_report(text, root, data, cases):
    """Generate additions from data and replace the superseded protocol prose."""
    root=Path(root)
    # Study-specific prose contains rounded descriptive facts. Bind them to the
    # recomputed artifacts as well as the input hash, and stop if they change.
    current={c:json.loads((root/c/'statistics.json').read_text()) for c in CONDITIONS}
    if max(CONDITIONS,key=lambda c:current[c]['icc_2_1'])!='clahe':
        raise ValueError('Review the ICC ranking prose before regenerating.')
    if max(CONDITIONS,key=lambda c:current[c]['weighted_kappa'])!='he':
        raise ValueError('Review the kappa ranking prose before regenerating.')
    if sorted(round(v['difference_sd'],1) for v in current.values())!=[5.4,5.6,5.7]:
        raise ValueError('Review the rounded difference SD prose.')
    actual=[]
    for c in CONDITIONS:
        with (root/c/'surface_agreement.csv').open() as handle:
            actual += [(c,r['identity']) for r in csv.DictReader(handle) if r['outside_loa']=='True']
    expected=[('raw','7 / distal'),('raw','9 / distal'),('he','7 / mesial'),('clahe','14 / mesial')]
    if sorted(actual)!=sorted(expected):
        raise ValueError('Review the named LoA review flags before regenerating.')
    for c,name,value in [('raw','apex',12.892),('he','mesial.cej',8.062),('clahe','apex',10.708)]:
        with (root/c/'error_decomposition.csv').open() as handle:
            rows=list(csv.DictReader(handle))
        largest=max(rows,key=lambda r:float(r['rms_displacement_px']))
        if largest['landmark']!=name or round(float(largest['rms_displacement_px']),3)!=value:
            raise ValueError('Review the per-landmark displacement prose.')
    history=json.loads((root/'protocol_history/history_evidence.json').read_text())
    created=datetime.fromisoformat(history['study_created_utc'].replace('Z','+00:00'))
    final_r1=datetime.fromisoformat(history['backups'][-1]['backup_time_utc'].replace('Z','+00:00'))
    r2_first=min(g['first_save_utc'] for g in history['round2_groups'])
    r2_last=max(g['last_save_utc'] for g in history['round2_groups'])
    parse=lambda x:datetime.fromisoformat(x.replace('Z','+00:00'))
    lower=(parse(r2_first)-final_r1).total_seconds()/3600
    upper=(parse(r2_last)-created).total_seconds()/3600
    old_paragraph=next(p for p in text.split('\n\n') if p.startswith('I returned for the second round'))
    protocol=(f'The saved evidence placed the two rounds about 13 hours apart on the same date, '
        f'2026-10-23 (UTC and local UTC-4). The current study was created at {created:%H:%M:%S} UTC, '
        f'and the complete Round 1 backup was saved at {final_r1:%H:%M:%S} UTC. '
        f'Round 2 saves ran from {parse(r2_first):%H:%M:%S} to {parse(r2_last):%H:%M:%S} UTC. '
        f'These give a conservative interval range of {lower:.2f}–{upper:.2f} hours; '
        'they do not give an exact interval for each tooth. My earlier description of “about one day” was incorrect. '
        'I used these time bounds because individual Round 1 timestamps were not available.\n\n'
        f'Before the analyzed collection, I completed an earlier RAW session with {history["excluded_records"]} readings on the same 15 registered locations. '
        'That study was archived when I restarted the workflow at my request. The specific reason was not recorded in the structured study log, '
        'so I cannot give a more detailed reason from those records. The archived session was complete by '
        f'{parse(history["backups"][0]["backup_time_utc"]):%H:%M:%S} UTC and is preserved separately in '
        '[excluded_raw_round1.json](protocol_history/excluded_raw_round1.json). It was not included in any reported agreement or contrast calculation. '
        f'The final RAW Round 1 minus archived RAW reading PBLmax difference was +{history["final_raw1_minus_excluded_raw1_mean_pp"]:.2f} pp '
        f'(sample SD {history["final_raw1_minus_excluded_raw1_sample_sd_pp"]:.2f} pp). '
        'I therefore saw these RAW teeth at least three times, including the excluded session. Keeping the final saved points unchanged during analysis '
        'does not mean that there was no earlier measurement attempt.\n\n'
        'Both rounds followed RAW → HE → CLAHE, as supported by the backup snapshots and Round 2 timestamps. '
        'The Round 2 tooth save order matched the seeded shuffled order for all three conditions; the Round 1 tooth order could not be verified. '
        'The short interval, earlier RAW exposure and fixed condition order could allow practice or memory to affect the results. '
        'These effects could increase apparent agreement and are mixed with the contrast comparison. Separate clicks should not be treated as proof of independent perception. '
        'In a future study, I would plan the interval and rotate the condition order across sessions.\n\n'
        '| Round 2 condition | First–last save (UTC) | First-to-last span (s) | Median consecutive-save interval (s) |\n'
        '| --- | --- | ---: | ---: |\n')
    for g in history['round2_groups']:
        protocol+=f'| {g["condition"].upper()} | {parse(g["first_save_utc"]):%H:%M:%S}–{parse(g["last_save_utc"]):%H:%M:%S} | {g["first_to_last_save_seconds"]:.0f} | {g["median_inter_save_seconds"]:.0f} |\n'
    total=(parse(r2_last)-parse(r2_first)).total_seconds()
    protocol+=f'\nThe first-to-last Round 2 save span was {total/60:.2f} minutes. These are save intervals, not directly measured time spent marking each tooth. '
    protocol+='The [history evidence](protocol_history/history_evidence.json) records the backup bounds and save order.'
    text=text.replace(old_paragraph,protocol)
    # Avoid describing reported rankings as causal contrast gains.
    text=text.replace('I marked each condition separately, so the comparison was based on repeated landmark placement rather than the same set of copied coordinates.',
        'I placed new clicks for each condition, rather than copying coordinates. However, the fixed RAW → HE → CLAHE order meant that the readings could still be affected by practice and recall.')
    text=text.replace('These operations changed the image intensity without changing the pixel grid.',
        'These operations changed the image intensity without changing the pixel grid. I interpreted the assignment’s “tile grid = 88” as an 8 × 8 tile grid.')
    supplement=paired_statistics(data)
    (root/'supplementary_statistics.json').write_text(json.dumps(supplement,indent=2,allow_nan=False)+'\n')
    lookup={(r['tooth_id'],r['condition'],r['round']):r for r in data}
    section=['### Tooth-level and clustered checks','',
        'I also compared worse-side PBLmax using one pair per tooth, so that this check did not count the two surfaces as separate teeth. The results below describe the same 15 teeth; they are a supplement to the surface results.', '',
        '| Condition | PBLmax ICC(2,1) | Tooth bias (pp) | Tooth 95% LoA (pp) | Correlation of mesial/distal round differences |',
        '| --- | ---: | ---: | --- | ---: |']
    for c,v in supplement['conditions'].items():
        section.append(f'| {c.upper()} | {v["tooth_icc"]:.3f} | {v["tooth_bias"]:+.3f} | {v["tooth_loa_lower"]:.3f} to {v["tooth_loa_upper"]:.3f} | {v["difference_correlation"]:.3f} |')
        y=np.array([v['tooth_round1'],v['tooth_round2']]).T;diff=y[:,1]-y[:,0]
        fig,ax=plt.subplots(figsize=(8,4.8),layout='constrained');ax.scatter(y.mean(1),diff)
        for val,label in [(v['tooth_bias'],'Bias'),(v['tooth_loa_lower'],'Lower LoA'),(v['tooth_loa_upper'],'Upper LoA')]:
            ax.axhline(val,ls='--',label=f'{label}: {val:.3f} pp')
        ax.set(xlabel='Mean tooth PBLmax (%)',ylabel='R2 − R1 (pp)',title=f'{c.upper()} tooth-level Bland–Altman: 15 teeth');ax.legend();ax.grid(alpha=.15)
        fig.savefig(root/c/'tooth_bland_altman.png',dpi=160);plt.close(fig)
    section+=['',f'I resampled whole teeth {supplement["repeats"]:,} times with replacement (seed {supplement["seed"]}), retaining both surfaces and rounds together. The percentile intervals below describe the pooled-surface ICC and mean surface bias under this resampling scheme. They do not correct the fixed condition order or the small single-image sample. A bootstrap interval need not be wider than the nominal ANOVA interval, so its upper endpoint alone does not prove that the nominal interval was too narrow.','',
        '| Condition | Tooth-cluster bootstrap surface ICC 95% interval | Tooth-cluster bootstrap surface bias 95% interval (pp) |', '| --- | --- | --- |']
    for c,v in supplement['conditions'].items():
        a,b=v['clustered_surface_icc_ci'];x,y=v['clustered_bias_ci']
        section.append(f'| {c.upper()} | {a:.3f} to {b:.3f} | {x:+.3f} to {y:+.3f} |')
    for c in CONDITIONS: section+=['',f'![{c.upper()} tooth Bland–Altman]({c}/tooth_bland_altman.png)']
    section+=['','### Stage counts and confusion matrices','',
        'The rows below show Round 1 stages and the columns show Round 2 stages for whole teeth. There were no Stage I teeth in either round. Although the weighting uses three possible classes, the observed tooth comparisons only distinguished II and III/IV.','',
        '| Condition | R1 stage | R2 I | R2 II | R2 III/IV |','| --- | --- | ---: | ---: | ---: |']
    all_confusion=[]
    for c,v in supplement['conditions'].items():
        for i,stage in enumerate(STAGES):
            counts=v['tooth_confusion'][i]
            section.append(f'| {c.upper()} | {stage} | {counts[0]} | {counts[1]} | {counts[2]} |')
            all_confusion.append(dict(condition=c,round1_stage=stage,round2_I=counts[0],round2_II=counts[1],round2_III_IV=counts[2]))
    write_csv(root/'tooth_stage_confusion.csv',all_confusion)
    mismatches=', '.join(f'{c.upper()} {v["tooth_stage_mismatches"]}/15' for c,v in supplement['conditions'].items())
    near=[(r,s) for r in data for s in ('mesial','distal') if min(abs(r['metrics'][s+'_pbl_pct']-b) for b in (15,33))<1]
    unique=len({(r['tooth_id'],s) for r,s in near})
    flagged=sum(r['metrics']['stage']=='III/IV' for r in data)
    section+=['',f'Tooth-stage disagreements were {mismatches}. The apparent difference in agreement therefore involved only a few teeth and could change in another sample. Across all 180 surface observations, {len(near)} were less than 1 pp from 15% or 33%, covering {unique} distinct tooth surfaces. Small placement changes near a boundary can change a stage. The engine raised its assignment “furcation / vertical defect review” flag for {flagged}/90 readings above 33%; these were review flags rather than confirmed defects.','']
    text=text.replace('### Comparing landmark placement across image conditions','\n'.join(section)+'\n### Comparing landmark placement across image conditions')
    text=text.replace('HE had the lowest Round 1–Round 2 coordinate RMSD and the lowest within-landmark variance in this sample.',
        'HE had the lowest observed Round 1–Round 2 coordinate RMSD and within-landmark variance, but the fixed reading order prevented attributing that difference to HE alone. The two measures contain the same information here: variance = RMSD²/2.')
    # Case-specific signed perturbations; preserve every individual trial in the CSV.
    sensitivity=list(csv.DictReader((root/'sensitivity.csv').open()))
    case_rows=[]
    for rank,case in enumerate(cases,1):
        t,c=case['tooth'],case['condition'];rows=[r for r in sensitivity if int(r['tooth_id'])==t and r['condition']==c and abs(int(r['shift_px'])) in (5,10)]
        case_rows.extend(dict(rank=rank,**r) for r in rows)
        plot_case(root,data,t,c,f'case_{rank}.png',f'Review rank {rank}')
        table=['',f'**T{t}, {c.upper()}: signed placement sensitivity.** Each row summarizes five one-landmark trials for that signed shift. “Maximum” means the largest absolute change across the five landmarks, not a single simultaneous shift of all five points. The [case-level CSV](case_sensitivity.csv) retains every landmark result.','',
            '| Shift (px) | Direction | Max absolute mesial Δ (pp) | Max absolute distal Δ (pp) | Max absolute PBLmax Δ (pp) | Rejected / 5 |',
            '| --- | --- | ---: | ---: | ---: | --- |']
        for shift in (-10,-5,5,10):
            for direction in ('parallel','normal'):
                selected=[r for r in rows if int(r['shift_px'])==shift and r['direction']==direction]
                valid=[r for r in selected if r['status']=='valid']
                maxima=[max(abs(float(r[key])) for r in valid) if valid else None for key in ('mesial_change_pp','distal_change_pp','max_change_pp')]
                values=['N/A' if v is None else f'{v:.3f}' for v in maxima]
                table.append(f'| {shift:+d} | {direction} | {values[0]} | {values[1]} | {values[2]} | {len(selected)-len(valid)} / {len(selected)} |')
        marker=f'![Review case {rank}](case_{rank}.png)';text=text.replace(marker,marker+'\n'+'\n'.join(table))
    assert len(case_rows)==200
    write_csv(root/'case_sensitivity.csv',case_rows)
    plot_case(root,data,7,'he','he_t7_flag.png','Additional LoA review (not another ranked tooth)')
    text=text.replace('### Comparing the image gradients near the bone crest',
        'The ranked T7 image shows RAW, which produced its largest residual. HE T7 mesial was also outside its own LoA; I included that distinct reading below so the ranking did not hide a flagged condition.\n\n![Additional HE T7 review](he_t7_flag.png)\n\n### Comparing the image gradients near the bone crest')
    # Retain the old full-window metric as a contrast control, add a nearby-crest window.
    image=Image.open('week2/sample_xrays/kaggle_dental_xray_1.jpg');edge=[]
    for c in CONDITIONS:
        enhanced=preprocess(image,c)
        for t in range(1,16):
            lm=landmarks_from_record(lookup[t,'raw',1]);tangent=tuple(float(d-m) for d,m in zip(lm.distal.bc,lm.mesial.bc))
            for s in ('mesial','distal'):
                off,intensity,gradient=crest_profile(enhanced,getattr(lm,s).bc,tangent)
                local=abs(off)<=3
                peak=float(off[np.argmax(gradient)])
                edge.append(dict(condition=c,tooth_id=t,side=s,full_peak_offset_px=peak,
                    full_peak_gradient=float(gradient.max()),local3_peak_gradient=float(gradient[local].max()),
                    full_peak_abs_offset_ge8=abs(peak)>=8,full_peak_at_boundary=abs(peak)==10))
    write_csv(root/'crest_gradient_diagnostics.csv',edge)
    edge_section=['','I added a restricted ±3 px check near the saved crest because the strongest full-window gradient could occur away from it. The table below also shows the location of the full-window peak. This extra check still uses unnormalized grayscale intensity, so the HE/CLAHE gain can increase the gradient without improving the correctness of the boundary. I did not use these gradients as evidence of superior landmark accuracy.','',
        '| Condition | Mean peak within ±3 px (gray/px) | Median absolute full-peak offset (px) | Full peak at ≥8 px / 30 | Full peak at ±10 px / 30 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for c in CONDITIONS:
        rows=[r for r in edge if r['condition']==c]
        edge_section.append(f'| {c.upper()} | {np.mean([r["local3_peak_gradient"] for r in rows]):.3f} | {np.median([abs(r["full_peak_offset_px"]) for r in rows]):.1f} | {sum(r["full_peak_abs_offset_ge8"] for r in rows)} | {sum(r["full_peak_at_boundary"] for r in rows)} |')
    text=text.replace('![Fixed-location crest profile](crest_profile.png)','')
    text=text.replace('## Discussion','\n'.join(edge_section)+'\n\n![Fixed-location crest profile](crest_profile.png)\n\n## Discussion')
    # Address systematic vs random error without treating a zero-containing interval as proof of absence.
    direction=('The tooth-cluster bootstrap intervals for overall surface bias included zero in each condition. '
        'I therefore did not find clear evidence of an overall directional PBL shift in this sample. '
        'The centered landmark residuals were larger than their mean drift magnitudes, so the variation was mainly heterogeneous across teeth. '
        'However, I could not conclude that the errors were purely random or that systematic error was absent. '
        'For example, the CLAHE apex had an average parallel shift of about 5.5 px toward the root direction, which still needed review. '
        'The short interval, earlier RAW session and fixed condition order could also affect agreement without appearing as a mean PBL shift.')
    text=text.replace('## Discussion','## Discussion\n\n'+direction,1)
    text=text.replace('CLAHE had the highest observed ICC and the highest average peak gradient, while HE had the highest stage agreement and the lowest coordinate variation between rounds.',
        'CLAHE had the highest observed ICC, while HE had the highest stage agreement and the lowest coordinate variation between rounds. These were descriptive rankings under a fixed reading order. The intensity-gradient results were a separate contrast control and did not establish better anatomical edge localization.')
    text=text.replace('planned interval between rounds would help evaluate', 'planned interval between rounds and counterbalanced condition order would help evaluate')
    text=text.replace('CLAHE had the highest ICC in this dataset, while HE had the highest stage agreement and the lowest coordinate variation between rounds.',
        'CLAHE had the highest observed ICC, while HE had the highest observed stage agreement and the lowest coordinate variation. The approximately 13-hour interval, prior RAW exposure and fixed RAW → HE → CLAHE order meant that these differences could not be attributed to contrast enhancement alone.')
    text=text.replace('| Five ranked review teeth and 2/5/10 px sensitivity | Included; only four surface differences exceed LoA |',
        '| Five ranked review teeth and 2/5/10 px sensitivity | Included, with per-case signed ±5/±10 px tables and an additional HE T7 overlay; four surface differences exceed LoA |')
    return text
