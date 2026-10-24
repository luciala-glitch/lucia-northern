"""Tooth-paired analyses and figures for the collected-study report.

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
        ax.annotate(name,p,xytext=(-7 if p[0] < a.mid_cej[0] else 7, -9 if name.endswith('cej') or name=='apex' else 10),textcoords='offset points',ha='right' if p[0] < a.mid_cej[0] else 'left',color='#00d5ff',fontsize=8,bbox=dict(facecolor='black',alpha=.3,edgecolor='none',pad=1))
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

