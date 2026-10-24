import json, csv, hashlib
from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from week3.exports import landmarks_from_record, validate_record
from week3.pbl_calculator import calculate_tooth_pbl
from week3.sensitivity import sensitivity, LANDMARK_NAMES
from week3.errors import decompose_displacements
from week3.image_processing import preprocess, crest_profile
from week3.analyze import write_csv, statistics_report, group_pairs, synthetic_cases
from week3.exports import json_export, csv_export, csv_import
from week3.comparison import compare_conditions

root=Path('week3/reports/collected_study')
source=root/'exports'/'measurements.json'
# This manuscript targets one frozen dataset. Fail loudly rather than retain stale
# editorial conclusions if the input changes; a new study requires a new report.
if hashlib.sha256(source.read_bytes()).hexdigest() != '4e9f6cac5410a14ded62961f383377861d0b8f03abaaa72859a30c45a2a3daa8':
    raise ValueError('This report is frozen to the audited 90-reading dataset; review prose before changing input.')
data=json.loads(source.read_text())
for r in data: validate_record(r)
manifest=json.loads((root/'exports'/'collection_manifest.json').read_text())
image_path=Path('week2/sample_xrays/kaggle_dental_xray_1.jpg')
assert hashlib.sha256(image_path.read_bytes()).hexdigest()==manifest['image_sha256']['kaggle_dental_xray_1.jpg']
with Image.open(image_path) as im:
    width,height=im.size
    for r in data:
        lm=landmarks_from_record(r)
        for point in (lm.mesial.cej,lm.mesial.bc,lm.distal.cej,lm.distal.bc,lm.apex):
            assert 0<=point[0]<width and 0<=point[1]<height

expected={(t,c,r) for t in range(1,16) for c in ('raw','he','clahe') for r in (1,2)}
identities=[(r['tooth_id'],r['condition'],r['round']) for r in data]
assert len(data)==90 and len(set(identities))==90 and set(identities)==expected
assert {r['image_id'] for r in data}=={'kaggle_dental_xray_1.jpg'}
assert json.loads(json_export(data))==data
assert csv_import(csv_export(data))==data
assert csv_import((root/'exports'/'measurements.csv').read_text())==data
for c in ('raw','he','clahe'):
    records=[dict(key=('study',r['image_id'],r['tooth_id']), round=r['round'], landmarks=landmarks_from_record(r), result=calculate_tooth_pbl(landmarks_from_record(r))) for r in data if r['condition']==c]
    target=root/c
    target.mkdir(exist_ok=True)
    statistics_report(group_pairs(records),target,c)
(root/'preprocessing_comparison.json').write_text(json.dumps(compare_conditions(data),indent=2)+'\n')
lookup={(r['tooth_id'],r['condition'],r['round']):r for r in data}
stats={c:json.loads((root/c/'statistics.json').read_text()) for c in ('raw','he','clahe')}
comparison=json.loads((root/'preprocessing_comparison.json').read_text())['conditions']
lines=['# Week 3 Report: Repeatability and Image Contrast in the PBL Calculator','', '## Introduction','', "For this week's project, I continued working on the periodontal bone loss (PBL) calculator from Week 2. The main goal was to examine how much the measurements changed when I marked the same teeth again, and whether image enhancement affected the placement of the landmarks. I also used the project to check the calculation method and how the software handled invalid points. This was intended to help identify areas that still needed improvement before considering broader use of the calculator.\n\nTo do this, I marked the same 15 teeth on one panoramic radiograph, `kaggle_dental_xray_1.jpg`, under three image conditions: Raw, global histogram equalization (HE), and CLAHE. I completed two rounds for each condition, which gave 90 saved tooth readings and 180 surface observations. All coordinates were kept in the original 2041 × 1024 image size. The tooth IDs were used to keep track of the selected teeth across the different conditions and rounds; they were not clinical tooth numbers. The data checks confirmed that each group contained the same 15 tooth IDs, with no missing or duplicate readings. I kept the saved points unchanged during the analysis.", '', '## Methods\n\n### Collecting the measurements\n\nFor each tooth, I selected the mesial and distal cementoenamel junctions (CEJs), the two bone crests, and one shared anatomical root apex. The calculator used the midpoint between the CEJs and the selected apex to define the long axis of the tooth. The bone-loss distance and root length were then measured along this axis. This helped keep the calculation tied to the direction of the root rather than using the straight-line distance between any two points.\n\nFor the contrast comparison, global HE used `equalizeHist`, while CLAHE used a clip limit of 2.0 and an 8 × 8 tile grid. These operations changed the image intensity without changing the pixel grid. I marked each condition separately, so the comparison was based on repeated landmark placement rather than the same set of copied coordinates.\n\nThe final software stage was based on the side with the higher PBL percentage. I used the assignment thresholds of less than 15%, 15–33% inclusive, and greater than 33%. These categories were used to compare the calculator outputs. They did not provide a full clinical diagnosis.', '', 'I returned for the second round after approximately one day. However, the first-round timestamps were not available, so the exact interval could not be confirmed from the saved records. The application supports blind reading and randomized tooth order, but there was no complete activity log showing the settings for every reading. I therefore kept these details as limitations of the measurement process.', '', '### Calculating PBL and checking the geometry','',
'The calculation used the following definitions, where `k` refers to either the mesial or distal side:\n\n```text\nm = (CEJ_mesial + CEJ_distal) / 2\nu = (apex − m) / ||apex − m||\nd_k = (BC_k − CEJ_k) · u\nL_k = (apex − CEJ_k) · u\nPBL_k = 100 × |d_k| / |L_k|\nPBL_max = max(PBL_mesial, PBL_distal)\n```\n\nBefore calculating the percentage, the program checked that `L_k > 0` and `0 ≤ d_k ≤ L_k`. The purpose of checking the signed distances first was to avoid accepting a crest that was above the CEJ or beyond the apex after taking absolute values. Invalid coordinates, an undefined axis, and invalid bone-crest positions produced specific error messages. Points lying on the same line were still accepted when the axis and projected root lengths were valid.', '',
'The program also included an optional crown landmark for the root-to-crown ratio check. Following the assignment, it gave a warning when the ratio was below 1.0 or above 2.5. However, the required export format did not include this extra point, so the ratio could not be checked from these 90 five-landmark records. The geometric checks helped identify invalid inputs, but they could not determine whether I had selected the correct anatomical boundary.', '',
'## Results\n\n### Agreement between the two rounds','', 'To compare the two rounds, I used the same 15 teeth, or 30 surfaces, within each condition. The table below presents ICC(2,1), quadratic weighted kappa, mean bias, and the 95% limits of agreement (LoA). All differences were calculated as Round 2 minus Round 1 and are reported in percentage points (pp). I included kappa for both the individual surfaces and the final tooth stage, because the final stage used the worse side of each tooth.', '', '| Condition | Surface ICC(2,1) | Surface weighted κ | Tooth weighted κ | Bias (pp) | 95% LoA (pp) |','| --- | ---: | ---: | ---: | ---: | --- |']
for c,s in stats.items():
 lines.append(f"| {c.upper()} | {s['icc_2_1']:.3f} | {s['weighted_kappa']:.3f} | {s['tooth_stage_quadratic_kappa']:.3f} | {s['bias']:+.3f} | {s['loa_lower']:.3f} to {s['loa_upper']:.3f} |")
lines += ['', 'The ICC calculation followed the requested two-way, absolute-agreement, single-measure model:\n\n```text\nICC(2,1) = (MS_subject − MS_error) /\n           (MS_subject + (k−1)MS_error + k(MS_round−MS_error)/n)\nn = 30 paired surfaces; k = 2 rounds\n```\n\nFor quadratic weighted kappa, the disagreement weights were `(i−j)²/4` across the three ordered stages, with `κ = 1 − observed weighted disagreement / expected weighted disagreement`. An undefined denominator was left undefined rather than treated as perfect agreement. For the Bland–Altman plots, the mean bias was `mean(R2−R1)`, and the limits were `bias ± 1.96 × sample SD`, using `ddof=1`. I used these limits to describe the spread in this sample; the small dataset did not establish that the differences had a normal distribution or constant variance. Because I was the only reader, the ICC results described my repeated readings and could not show agreement between different readers.']
lines+=['','From the results in the table, CLAHE had the highest ICC, while HE had the highest weighted kappa for both surfaces and final tooth stages. This suggested that the conditions did not perform in the same way for every comparison. For example, the condition with the highest continuous agreement did not also have the highest agreement on stage categories.\n\nThe mean bias was small for all three conditions, but the standard deviation of the differences was about 5.4–5.7 pp. The agreement limits were therefore still around ±11 pp. This showed that a small average change could occur even when some individual readings changed quite a bit. I did not set an acceptable difference before collecting the data, so I could not use the results to declare that the measurements were sufficiently reliable for clinical use. The two surfaces also shared the same tooth and apex, meaning they were related observations rather than 30 independent teeth.','']
lines += ['', 'I also included the ICC confidence intervals calculated by the program. These intervals assumed independent subjects and were not adjusted for the two surfaces coming from the same tooth. As a result, they could make the estimates appear more precise than they really were. The table below should therefore be read together with this limitation.', '', '| Condition | Nominal ICC 95% interval | Difference SD (pp) | Difference–mean slope |', '| --- | --- | ---: | ---: |']
for c,s in stats.items():
 lines.append(f"| {c.upper()} | {s['icc_ci_lower']:.3f} to {s['icc_ci_upper']:.3f} | {s['difference_sd']:.3f} | {s['difference_mean_slope']:.3f} |")
lines.append('')
for c in stats: lines += [f'![{c.upper()} Bland–Altman plot]({c}/bland_altman.png)','']
lines+=['### Comparing landmark placement across image conditions','','| Condition | Coordinate RMSD vs Raw (px) | R1–R2 coordinate RMSD (px) | Within-landmark coordinate variance (px²) |','| --- | ---: | ---: | ---: |']
for c,v in comparison.items():
 cross=v['coordinate_rmsd_vs_raw_px']
 lines.append(f"| {c.upper()} | {'Reference' if cross is None else f'{cross:.3f}'} | {v['round_coordinate_rmsd_px']:.3f} | {v['mean_within_landmark_coordinate_variance_px2']:.3f} |")
lines+=['','The comparison included 30 complete tooth-and-round groups, with Raw, HE, and CLAHE present in each group. I calculated coordinate RMSD as `sqrt(mean(dx²+dy²))` across the five landmarks. The within-landmark variance was the average of the summed x and y sample variances over the two rounds.\n\nHE had the lowest Round 1–Round 2 coordinate RMSD and the lowest within-landmark variance in this sample. This meant that my points moved less between the two HE readings on average. However, this did not show that the points were closer to the correct anatomical locations. There were no expert reference points to make that comparison.','']
ranked={}
all_sensitivity=[]
for c in stats:
 pairs=[]
 for t in range(1,16):
  a=landmarks_from_record(lookup[t,c,1]); b=landmarks_from_record(lookup[t,c,2]); pairs.append((a,b))
  delta=[getattr(calculate_tooth_pbl(b),s).pbl_pct-getattr(calculate_tooth_pbl(a),s).pbl_pct for s in ('mesial','distal')]
  score=max(abs(x-stats[c]['bias']) for x in delta)
  if t not in ranked or score>ranked[t]['score']: ranked[t]=dict(tooth=t,condition=c,score=score,mesial_pp=delta[0],distal_pp=delta[1])
  all_sensitivity += [dict(condition=c,tooth_id=t,**r) for r in sensitivity(a)]
 write_csv(root/c/'error_decomposition.csv',decompose_displacements(pairs))
lines += ['### Changes in individual landmarks', '', "To understand where the differences came from, I separated each landmark's movement into directions parallel and normal to the Round 1 tooth axis. A positive parallel movement pointed toward the apex, and the normal direction was `(−u_y,u_x)`. The calculation separated the average movement from the remaining variation using `total RMS² = mean drift magnitude² + centered residual RMS²`, with population normalization. The purpose of this step was to see whether there was a common direction of movement or whether the changes varied more across teeth. It did not, by itself, prove that the remaining variation was random noise.", '', '| Condition | Landmark | Mean parallel (px) | Mean normal (px) | Total RMS (px) | Drift magnitude (px) | Centered residual RMS (px) |', '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
for c in stats:
 with (root/c/'error_decomposition.csv').open() as f:
  for r in csv.DictReader(f):
   lines.append(f"| {c.upper()} | {r['landmark']} | {float(r['mean_parallel_shift_px']):.3f} | {float(r['mean_normal_shift_px']):.3f} | {float(r['rms_displacement_px']):.3f} | {float(r['mean_drift_magnitude_px']):.3f} | {float(r['centered_residual_rms_px']):.3f} |")
lines += ['', 'Based on this table, the apex had the largest displacement RMS for RAW (12.892 px) and CLAHE (10.708 px), while the mesial CEJ had the largest RMS for HE (8.062 px). This helped identify which landmarks needed closer review in each condition. It also showed why looking only at the average PBL difference would leave out some of the changes in point placement.', '']
write_csv(root/'sensitivity.csv',all_sensitivity)
summaries=[]
for size in (2,5,10):
 for direction in ('parallel','normal'):
  rows=[r for r in all_sensitivity if abs(r['shift_px'])==size and r['direction']==direction]
  vals=[abs(r['max_change_pp']) for r in rows if r['status']=='valid']
  summaries.append(dict(shift_px=size,direction=direction,trials=len(rows),rejected=sum(r['status']!='valid' for r in rows),mean_abs_change_pp=float(np.mean(vals)) if vals else None,max_abs_change_pp=max(vals) if vals else None,stage_changes=sum(r.get('stage_changed') is True for r in rows)))
write_csv(root/'sensitivity_summary.csv',summaries)
lines+=['### Testing sensitivity to small placement changes','','For the sensitivity test, I used the 45 Round 1 geometries as the starting points. The analysis moved one landmark at a time by ±2, ±5, or ±10 pixels, either parallel or normal to the original axis. The program recalculated the long axis and both PBL percentages after each change. This gave 2,700 simulated trials, which were kept separate from the 90 saved readings.\n\nThe table below shows the absolute change in the worse-side PBL percentage. Invalid placements would be recorded as rejected trials instead of being counted as zero change.','','| Shift (px) | Direction | Mean absolute Δ (pp) | Maximum absolute Δ (pp) | Rejected / trials |','| --- | --- | ---: | ---: | --- |']
for r in summaries: lines.append(f"| {r['shift_px']} | {r['direction']} | {r['mean_abs_change_pp']:.3f} | {r['max_abs_change_pp']:.3f} | {r['rejected']} / {r['trials']} |")
lines+=['','### Reviewing the five teeth with the largest differences','','I then selected five teeth for a closer comparison of their saved landmarks. For each tooth, I took the largest absolute surface difference after subtracting the mean bias for that condition. I ranked the teeth by this value and included the condition responsible for the largest difference in the table below.\n\nOnly four surface differences were outside their condition-specific LoA: RAW T7 distal, RAW T9 distal, HE T7 mesial, and CLAHE T14 mesial. Therefore, the five ranked teeth should not all be described as outliers. They were selected to help review the larger differences, and the same tooth could have a flagged surface in more than one condition.','','| Rank | Tooth | Condition | Mesial Δ (pp) | Distal Δ (pp) |','| --- | --- | --- | ---: | ---: |']
cases=sorted(ranked.values(),key=lambda r:r['score'],reverse=True)[:5]
write_csv(root/'worst_cases.csv',cases)
image=Image.open('week2/sample_xrays/kaggle_dental_xray_1.jpg')
for rank,row in enumerate(cases,1):
 t,c=row['tooth'],row['condition']; a=landmarks_from_record(lookup[t,c,1]); b=landmarks_from_record(lookup[t,c,2])
 lines.append(f"| {rank} | T{t} | {c.upper()} | {row['mesial_pp']:+.3f} | {row['distal_pp']:+.3f} |")
 fig,ax=plt.subplots(figsize=(6,6),layout='constrained'); ax.imshow(preprocess(image,c),cmap='gray',vmin=0,vmax=255); points=[]
 for name in LANDMARK_NAMES:
  def point(lm):
   if name=='apex': return np.array(lm.apex)
   side,key=name.split('.'); return np.array(getattr(getattr(lm,side),key))
  p,q=point(a),point(b); points.extend([p,q]); ax.scatter(*p,c='#00d5ff',s=20); ax.scatter(*q,c='#ffae36',s=20); ax.annotate('',xy=q,xytext=p,arrowprops={'arrowstyle':'->','color':'#ffae36'}); ax.annotate(name,p,xytext=(4,5),textcoords='offset points',color='#00d5ff',fontsize=8)
 u=np.array(calculate_tooth_pbl(a).long_axis_vector); ax.plot([a.mid_cej[0],a.apex[0]],[a.mid_cej[1],a.apex[1]],color='#79ff79',label='R1 axis')
 for side in (a.mesial,a.distal):
  p=np.array(side.cej); bc=np.array(side.bc); projection=p+np.dot(bc-p,u)*u; ax.plot([p[0],projection[0]],[p[1],projection[1]],color='#ff70b7'); ax.plot([bc[0],projection[0]],[bc[1],projection[1]],'--',color='#ff70b7')
 pts=np.array(points); ax.set_xlim(pts[:,0].min()-60,pts[:,0].max()+60); ax.set_ylim(pts[:,1].max()+45,pts[:,1].min()-45); ax.set_title(f'Rank {rank}: T{t}, {c.upper()}\nCyan R1 / orange R2; manually annotated shared apex'); ax.legend(); fig.savefig(root/f'case_{rank}.png',dpi=150); plt.close(fig)
lines+=['','The figures below show the points from both rounds on the same tooth. Cyan represents Round 1, orange represents Round 2, and the arrows show how the points moved. The green line is the Round 1 long axis, while the pink lines show the projected distances and lateral components. These figures help show where the readings changed, but they do not confirm the reason for the change. In particular, an expert has not confirmed whether these cases involved obscured CEJs, overlapping roots, or another anatomical difficulty.']
for rank in range(1,6): lines += ['',f'![Review case {rank}](case_{rank}.png)']
edge=[]
profiles={}
for c in stats:
 enhanced=preprocess(image,c)
 for t in range(1,16):
  lm=landmarks_from_record(lookup[t,'raw',1]); tangent=tuple(float(d-m) for d,m in zip(lm.distal.bc,lm.mesial.bc))
  for side in ('mesial','distal'):
   off,intensity,gradient=crest_profile(enhanced,getattr(lm,side).bc,tangent)
   if t==1 and side=='mesial': profiles[c]=(off,intensity,gradient)
   edge.append(dict(condition=c,tooth_id=t,side=side,peak_gradient=float(gradient.max()),peak_offset=float(off[np.argmax(gradient)])))
write_csv(root/'crest_edge_metrics.csv',edge)
fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
for c,(offsets,intensity,gradient) in profiles.items():
 axes[0].plot(offsets,intensity,label=c.upper())
 axes[1].plot(offsets,gradient,label=c.upper())
for ax in axes:
 ax.set_xlabel('Offset from fixed RAW R1 crest (px)'); ax.legend(); ax.grid(alpha=.15)
axes[0].set_ylabel('Intensity (8-bit gray)'); axes[1].set_ylabel('|dI/ds| (gray levels/px)')
fig.suptitle('T1 mesial crest: fixed-location contrast control'); fig.savefig(root/'crest_profile.png',dpi=160); plt.close(fig)

lines+=['','### Comparing the image gradients near the bone crest','','For the image-gradient comparison, I kept the RAW Round 1 crest locations fixed across all three image conditions. This allowed the analysis to compare the intensity changes without also changing the sampling locations. Each profile covered ±10 original pixels at one-pixel intervals, perpendicular to the line joining the two bone crests.\n\nThe line between the crests was used as an approximate tangent because an expert local bone contour was not available. This was a limitation of the method. A higher peak gradient could reflect a stronger edge, but it could also include amplified noise.','','| Condition | Profiles | Mean peak gradient (gray levels/px) |','| --- | ---: | ---: |']
for c in stats:
 vals=[r['peak_gradient'] for r in edge if r['condition']==c]; lines.append(f'| {c.upper()} | {len(vals)} | {np.mean(vals):.3f} |')
lines+=['','## Discussion','','From the different comparisons, I found that the small average PBL changes did not mean that every landmark stayed in the same place. Some changes were larger for the apex, while others were larger for the CEJ or bone crest. The displacement analysis helped separate the average direction of movement from the remaining variation, but two rounds without expert reference points were not enough to determine the cause of these differences. I therefore could not conclude that all of the variation was random or that there was no systematic placement bias.\n\nThe image comparisons also showed why more than one measure was useful. CLAHE had the highest observed ICC and the highest average peak gradient, while HE had the highest stage agreement and the lowest coordinate variation between rounds. Based on these results, I could compare how the conditions behaved in this sample, but I could not identify one condition as the most accurate method for locating the anatomical boundaries.', '', 'One limitation of this project was the size and source of the dataset. I measured only 15 selected teeth from one image, and I was the only reader. The two surfaces of each tooth shared an apex, so they were not independent observations. There were also no expert reference points, and some timing information from the first round was unavailable. These factors limited how broadly I could apply the findings.\n\nThis report used only the new 90 readings. The earlier Week 2 measurements and the synthetic examples were kept separate. I also kept the original points unchanged when a larger difference appeared, because changing one round to match the other would no longer show the repeatability of the original readings.', '', 'Another limitation was that the clinical categories requested in the assignment had not been confirmed by an expert. The figures could be used to review the saved points, but I could not label them as verified examples of restoration-obscured CEJs, overlapping molar roots, or tilted teeth. I included separate synthetic diagrams to explain these possible mechanisms. They were examples of how the geometry could change, rather than evidence that the same problem occurred in a particular measured tooth.', '', 'For future work, I would first ask someone with experience in dental radiographs to review the ambiguous landmarks and identify suitable clinical examples. After that, a larger study with more images, more readers, and a planned interval between rounds would help evaluate whether the patterns found here also appeared in other measurements. The dataset and backup details for this project are recorded in [COLLECTION_CHECK.md](COLLECTION_CHECK.md).']
lines += ['', '![Fixed-location crest profile](crest_profile.png)', '', '### Examples of possible geometric errors', '', 'The diagram below uses made-up coordinates to show three situations: a shifted CEJ under an obscuring restoration, a different apex selection when roots overlap, and a tilted tooth with lateral crest displacement. The purpose of these examples was to make the effect of point placement easier to see. They were not additional patient measurements or confirmed explanations for the five review cases above.', '', '![Synthetic failure mechanisms](synthetic_failure_cases.png)']
synthetic_cases(root)
from week3.reports.collected_study.verification import verify_evidence
verification = verify_evidence(root)
verification_date = verification['checked_local_date']
coverage=json.loads((root/'full_coverage.json').read_text())
engine=coverage['files']['week3/pbl_calculator.py']['summary']
week3_log=(root/'week3_test_results.txt').read_text()
project_log=(root/'project_test_results.txt').read_text()
frontend_log=(root/'frontend_test_results.txt').read_text()
import re
week3_count=int(re.search(r'(\d+) passed',week3_log).group(1))
project_count=int(re.search(r'(\d+) passed',project_log).group(1))
frontend_count=int(re.search(r'pass (\d+)',frontend_log).group(1))
assert 'fail 0' in frontend_log
assert (week3_count,project_count,frontend_count)==tuple(verification['counts'][k] for k in ('week3','project','frontend'))
branch_pct=100*engine['covered_branches']/engine['num_branches']
assert engine['missing_branches']==0 and engine['num_branches']>0
lines += ['', '## Software Testing', '', f'The saved automated checks dated {verification_date} gave **{week3_count} passing Week 3 Python tests**, **{project_count} passing project Python tests**, and **{frontend_count} passing frontend logic tests**. The PBL engine covered **{engine["covered_branches"]}/{engine["num_branches"]} branches ({branch_pct:.0f}%)** and {engine["covered_lines"]}/{engine["num_statements"]} statements. This met the branch coverage target in the assignment. However, passing software tests did not confirm that the anatomical points were correct or that the calculator was ready for clinical use.', '', 'The tests covered projected geometry, boundary values, statistical calculations, JSON/CSV round trips, report generation, local record storage, and the frontend coordinate logic. I included the saved [Week 3 test output](week3_test_results.txt), [project test output](project_test_results.txt), [frontend test output](frontend_test_results.txt), and [coverage JSON](full_coverage.json) so the results could be checked alongside the report.', '', '## Data Files and Reproduction', '', f'Input JSON SHA-256: `{hashlib.sha256(source.read_bytes()).hexdigest()}`.', '', 'I saved the same 90 readings in [JSON](exports/measurements.json) and [CSV](exports/measurements.csv) formats. The [collection manifest](exports/collection_manifest.json) contains the registered tooth locations, image checksum, and available save times. The source image is the attributed sample in `week2/sample_xrays`. These files keep the measurements used in this report together so that another person can check the calculations.', '', 'The report can be regenerated from the repository root using the following commands:', '', '```bash', 'source .venv/bin/activate', 'python -m pip install -r week3/requirements.txt', 'MPLCONFIGDIR=/tmp/pbl-week3-matplotlib python -m week3.reports.collected_study.build_report', '```', '', 'The report script checks the 15-tooth × 3-condition × 2-round dataset, recalculates the stored results, and checks that the JSON and CSV files agree. It then regenerates the statistics, five review figures, sensitivity trials, displacement tables, and crest profiles. This script is frozen to the audited input JSON checksum, so changing the data stops generation rather than keeping old editorial conclusions. The verification manifest also checks hashes of the saved logs and relevant source files; regenerating the report does not rerun the tests. The evidence date above is the recorded test date, not the generation date. If the code changes, the test commands in the Week 3 README should be run first so that the test records used in the report are also updated.', '', '## Summary of the Week 3 Work', '', '| Deliverable | Current local status |', '| --- | --- |', '| ICC, weighted kappa, Bland–Altman and 95% LoA | Included for all three conditions |', '| Five ranked review teeth and 2/5/10 px sensitivity | Included; only four surface differences exceed LoA |', '| Restoration/overlap/tilt mechanisms | Synthetic examples included; actual clinical category verification remains unavailable |', '| Independent Raw/HE/CLAHE localization comparison | Complete: same 15 teeth, both rounds |', '| Crest edge profiles | Included, with chord-tangent proxy limitation |', '| Typed engine, guardrails and branch target | Verified by current tests and coverage |', '| Validated empirical JSON and CSV | Included in exports/ |', '| Public repository and PR | Not published by this task; requires final repository review |', '', '## Conclusion', '', "For this week's work, I completed the planned two-round measurements for 15 teeth under Raw, HE, and CLAHE conditions. I used these readings to examine continuous PBL agreement, stage agreement, changes in the individual landmarks, and sensitivity to small placement errors. CLAHE had the highest ICC in this dataset, while HE had the highest stage agreement and the lowest coordinate variation between rounds.\n\nThe main finding was that small average differences could still occur alongside larger changes in individual readings. This helped show which parts of the measurement process needed further attention, especially the selection of ambiguous landmarks. The results were useful for evaluating this version of the calculator, but they were not enough to show that one enhancement method was more accurate or that the system had been clinically validated."]
lines += ['', '## References', '', '- Absolute-agreement and single-measure ICC terminology: [Pingouin ICC documentation](https://pingouin-stats.org/generated/pingouin.intraclass_corr.html). The project implements its own ANOVA calculation; it does not call Pingouin.', '- Quadratic weighted agreement: [scikit-learn Cohen kappa documentation](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html). The project implements its own fixed-class calculation.', '- Contrast transforms: [OpenCV histogram equalization and CLAHE](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html).', '- Original source/license attribution: [sample image README](../../../week2/sample_xrays/README.md).', '- Exact assignment: [Week 3 requirements](ASSIGNMENT_REQUIREMENTS.txt).']
from week3.reports.collected_study.review_supplement import amend_report
report_text = amend_report('\n'.join(lines)+'\n', root, data, cases)
from week3.reports.collected_study.radiographic_cases import build_cases
build_cases(root)
report_text = report_text.replace('This report used only the new 90 readings.', 'The primary statistical analysis used only the new 90 readings.')
report_text = report_text.replace('### Examples of possible geometric errors',
    '### Existing radiographic examples\n\nI also reviewed the images and readings already saved in the project. The [radiographic case appendix](radiographic_cases/RADIOGRAPHIC_CASES.md) shows a restoration affecting CEJ identification (Week 2 img10-T3), an upper molar with partly superimposed/indistinct root outlines (current T9), and an angulated tooth (current T7). Each figure uses actual saved Round 1 and Round 2 coordinates. These are visual screening labels rather than expert reference diagnoses. The legacy restoration example retains its original six-point format and remains outside every main statistic; I did not invent a shared anatomical apex. No new markings were required to make these figures.\n\n### Examples of possible geometric errors')
report_text = report_text.replace('| Restoration/overlap/tilt mechanisms | Synthetic examples included; actual clinical category verification remains unavailable |',
    '| Restoration/overlap/tilt mechanisms | Existing-image screening examples and observed vectors in the appendix, plus synthetic mechanisms; restoration example uses legacy six-point data outside the main statistics |')
report_text = report_text.replace('| Public repository and PR | Not published by this task; requires final repository review |',
    '| GitHub submission | [My repository and pull request links](SUBMISSION.md) |')
(root/'WEEK3_COLLECTED_REPORT.md').write_text(report_text)
print('Wrote report, five overlays, 2700 sensitivity trials, decomposition and 90 crest profiles.')
print('Cases:',cases)
