"""Illustrate actual saved reading differences on existing radiographs.

One legacy six-point case is contextual only, never pooled with the 90 readings.
No new anatomical landmarks or reader observations are manufactured here.
"""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from week3.analyze import write_csv

ROOT=Path('week3/reports/collected_study')


def build_cases(root=ROOT):
    root=Path(root);out=root/'radiographic_cases';out.mkdir(exist_ok=True)
    study=json.loads((root/'exports/measurements.json').read_text())
    with Path('week2/measurements.csv').open() as f:
        legacy=list(csv.DictReader(f))
    # Resolve the latest saved record per original round, as in legacy analysis.
    legacy.sort(key=lambda r:r['timestamp_utc'])
    selected={r['round']:r for r in legacy if r['tooth_id']=='img10-T3'}
    specs=[dict(key='restoration',title='Extensive restoration / difficult CEJ identification',
        image='kaggle_dental_xray_10.jpg',tooth='Week 2 img10-T3',source='legacy_six_point',
        bounds=(690,865,165,495),roi=(737,379,88,66),
        note='Radiopaque restoration occupies the crown/cervical region. The natural CEJ is difficult to separate from its outline. Material and restoration type are not identified from this image.',
        records=[selected['Round 1'],selected['Round 2']]),
        dict(key='root_overlap',title='Upper molar / projected root-outline overlap',
        image='kaggle_dental_xray_1.jpg',tooth='Week 3 T9',source='current_shared_apex',
        bounds=(1380,1565,325,605),roi=(1440,370,90,100),
        note='The upper molar shows multiple root shadows with indistinct and partly superimposed projected boundaries. This is a visual screening example, not confirmation of the number or 3D relationship of the roots.',
        records=[next(r for r in study if r['tooth_id']==9 and r['condition']=='raw' and r['round']==q) for q in (1,2)]),
        dict(key='tilted',title='Markedly angulated tooth / projected distances',
        image='kaggle_dental_xray_1.jpg',tooth='Week 3 T7',source='current_shared_apex',
        bounds=(300,585,490,745),roi=(365,548,150,125),
        note='The saved CEJ-to-apex axis is markedly oblique to the image vertical. The diagram compares direct segments and axial projections without claiming an ideal anatomical reference.',
        records=[next(r for r in study if r['tooth_id']==7 and r['condition']=='raw' and r['round']==q) for q in (1,2)])]
    def points(case,record):
        if case['source']=='legacy_six_point':
            return {s+'.'+name:np.array([int(record[f'{s}_{key}_x']),int(record[f'{s}_{key}_y'])],float)
                    for s in ('mesial','distal') for name,key in [('cej','cej'),('bc','bone_crest'),('tip','root_tip')]}
        lm=record['landmarks']
        return {**{s+'.'+k:np.array(lm[s][k],float) for s in ('mesial','distal') for k in ('cej','bc')},'apex':np.array(lm['apex'],float)}
    vector_rows=[];sources=[];metric_rows=[]
    fig,axes=plt.subplots(3,2,figsize=(12,17),layout='constrained')
    for i,case in enumerate(specs):
        image_path=Path('week2/sample_xrays')/case['image']
        image=Image.open(image_path)
        first,second=(points(case,r) for r in case['records'])
        for j,ax in enumerate(axes[i]):
            ax.imshow(image,cmap='gray',vmin=0,vmax=255)
            x0,x1,y0,y1=case['bounds'];ax.set_xlim(x0,x1);ax.set_ylim(y1,y0)
            ax.set_xlabel('Original x (px)');ax.set_ylabel('Original y (px)')
            if j==0:
                ax.add_patch(Rectangle(case['roi'][:2],*case['roi'][2:],fill=False,ec='#ecb731',lw=1.5,ls='--'))
                ax.set_title(f'{case["tooth"]}: original source\n{case["title"]}',fontsize=10)
                continue
            for k,p in first.items():
                q=second[k];delta=q-p
                vector_rows.append(dict(case=case['key'],source=case['source'],tooth=case['tooth'],image=case['image'],landmark=k,round1_x=int(p[0]),round1_y=int(p[1]),round2_x=int(q[0]),round2_y=int(q[1]),dx_px=float(delta[0]),dy_px=float(delta[1]),displacement_px=float(np.linalg.norm(delta))))
                ax.scatter(*p,c='#00cce7',s=24,zorder=4);ax.scatter(*q,c='#ff9d24',s=24,zorder=4)
                ax.annotate('',xy=q,xytext=p,arrowprops=dict(arrowstyle='->',color='#ff9d24',lw=1.8))
                ax.annotate(k,p,xytext=(4,5),textcoords='offset points',color='#00cce7',fontsize=7)
            mid=(first['mesial.cej']+first['distal.cej'])/2
            if case['source']=='current_shared_apex':
                end=first['apex'];u=np.array(case['records'][0]['long_axis_vector'])
                ax.plot([mid[0],end[0]],[mid[1],end[1]],c='#70ef70',label='R1 anatomical axis')
                for side in ('mesial','distal'):
                    cej,bc=first[side+'.cej'],first[side+'.bc'];proj=cej+np.dot(bc-cej,u)*u
                    ax.plot([cej[0],bc[0]],[cej[1],bc[1]],'--',c='#aaa',lw=1)
                    ax.plot([cej[0],proj[0]],[cej[1],proj[1]],c='#ff70b7',lw=2)
                    ax.plot([bc[0],proj[0]],[bc[1],proj[1]],'--',c='#ff70b7',lw=1)
                    projected=100*np.dot(bc-cej,u)/np.dot(end-cej,u)
                    euclidean=100*np.linalg.norm(bc-cej)/np.linalg.norm(end-cej)
                    metric_rows.append(dict(case=case['key'],tooth=case['tooth'],side=side,round=1,projected_pct=float(projected),euclidean_pct=float(euclidean)))
                subtitle='Cyan R1 / orange R2; green axis / pink projection'
            else:
                # Show the two original root-tip guides, never invent a shared apex.
                for side in ('mesial','distal'):
                    cej,tip=first[side+'.cej'],first[side+'.tip']
                    ax.plot([cej[0],tip[0]],[cej[1],tip[1]],'--',c='#70ef70',lw=1)
                subtitle='Legacy: 2 saved root tips; no shared apex inferred'
            ax.set_title(f'{case["tooth"]}: saved R1 → R2 vectors\n{subtitle}',fontsize=10)
        sources.append(dict(case=case['key'],image=case['image'],image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),tooth=case['tooth'],source=case['source'],screening_observation=case['note'],records=case['records']))
    fig.suptitle('Existing radiographic examples: original crops and observed placement vectors\nVisual screening labels; not expert reference annotations',fontsize=13)
    fig.savefig(out/'existing_radiographic_examples.png',dpi=160);plt.close(fig)
    write_csv(out/'observed_vectors.csv',vector_rows)
    write_csv(out/'projection_comparison.csv',metric_rows)
    (out/'source_records.json').write_text(json.dumps(sources,indent=2)+'\n')
    lines=['# Existing Radiographic Case Examples','',
        'I reviewed the images and saved coordinates already available in the project before asking for any additional marking. I selected the following examples to illustrate the three difficulties in the assignment. These are visual screening interpretations, not independently confirmed clinical labels or proof that a particular feature caused a placement difference.','',
        '| Requested difficulty | Existing source | What is visible | Re-marking needed for this figure? |',
        '| --- | --- | --- | --- |',
        '| Restoration affecting CEJ identification | Week 2 img10-T3, sample image 10 | Extensive radiopaque restoration in the crown/cervical region; the natural CEJ is difficult to distinguish from the restoration outline. I do not identify the material or call it a confirmed crown margin. | No: two saved six-point readings are available. |',
        '| Multiple/overlapping molar root outlines | Week 3 T9, sample image 1, RAW | Multiple upper-molar root shadows with indistinct/partly superimposed boundaries. Root count and 3D anatomy cannot be confirmed from this view. | No: both five-point readings are available. |',
        '| Angulated tooth | Week 3 T7, sample image 1, RAW | The tooth and saved long axis are visibly oblique to the image vertical. | No: both five-point readings are available. |','',
        '![Original crops and observed error vectors](existing_radiographic_examples.png)','',
        'Cyan points are the original Round 1 clicks and orange points are Round 2. Every orange vector is exactly R2 minus R1 in original pixels. The yellow source boxes identify broad review regions; they are not newly selected anatomical points. The arrows show observed placement differences, not error relative to a known true point.','',
        'For the two Week 3 cases, green is the saved shared-apex long axis, pink is the axial crest projection, and gray dashed segments show the direct CEJ-to-crest distance. For the legacy restoration example, dashed green lines connect each saved CEJ to its original side-specific root tip. Week 2 did not record one shared anatomical apex. I have not invented one or treated those two tips as a new shared-apex reading.','',
        '## Current-case projection comparison','',
        'For the two current RAW Round 1 readings, the table compares the projected PBL ratio with a direct Euclidean-distance ratio using the same saved points. Differences demonstrate the effect of geometry, not which reading is anatomically correct.','',
        '| Tooth | Side | Projected PBL (%) | Euclidean ratio (%) |','| --- | --- | ---: | ---: |']
    for r in metric_rows:lines.append(f'| {r["tooth"]} | {r["side"]} | {r["projected_pct"]:.3f} | {r["euclidean_pct"]:.3f} |')
    lines+=['','## Source and analysis boundaries','',
        'The main agreement statistics still use only the 90 current readings. The two Week 2 restoration readings are a contextual failure-case illustration, have an unknown enhancement condition, and are not added to ICC, kappa, Bland–Altman, RMSD, sensitivity-cohort counts or the current study database. This appendix therefore does not require redoing the existing 15-tooth collection. If an additional strict five-point empirical restoration study were requested, it would be a separately planned collection, not a retroactive replacement of these points.','',
        'The [source records](source_records.json) preserve which saved observations were plotted. The [vector CSV](observed_vectors.csv) contains every displayed displacement and the [projection CSV](projection_comparison.csv) contains the current-case ratios. The case labels describe the visible radiographic features; they do not claim expert certification.','',
        'The distinction between a visible restoration and an identifiable natural CEJ matters: restorations may hide the CEJ, and a restoration outline should not silently be treated as the anatomical junction. See [the radiological assessment around restorations study](https://pmc.ncbi.nlm.nih.gov/articles/PMC9831839/). Panoramic superimposition also limits root interpretation; see [the panoramic-versus-CBCT root evaluation study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10672905/). These papers explain the screening criteria; they do not certify the category or points in these sample images.','',
        'Sample image attribution is in [the original image README](../../../../week2/sample_xrays/README.md).']
    (out/'RADIOGRAPHIC_CASES.md').write_text('\n'.join(lines)+'\n')
    return out/'RADIOGRAPHIC_CASES.md'


if __name__=='__main__':
    print(build_cases())
