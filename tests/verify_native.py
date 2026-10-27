"""Run on K3: deterministic full-network tests and causal GF clamp experiment."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def run(block):
    lines=f'100 1 0 0 0 0 0 {block}\n200 1 1 1 0 0 0 {block}\n'
    p=subprocess.run([str(ROOT/'bin/siliconfly-brain'),str(ROOT/'data')],input=lines,
        text=True,capture_output=True,check=True,timeout=30)
    return [json.loads(line) for line in p.stdout.splitlines()]

a,b,c=run(0),run(0),run(1)
assert [{k:v for k,v in t.items() if k!='step_us'} for t in a]==[{k:v for k,v in t.items() if k!='step_us'} for t in b], 'Seeded determinism'
assert a[0]['gf_events']==0 and a[1]['gf_events']>0, 'Stimulus should drive GF'
assert c[1]['gf_events']==0 and c[1]['loom_hz']>50, 'GF clamp must preserve upstream visual response'
assert a[1]['neurons']==139255 and a[1]['edges']==15091983 and a[1]['sim_ms']==300
report=dict(passed=True,baseline={k:v for k,v in a[0].items() if k!='spikes'},
    stimulated={k:v for k,v in a[1].items() if k!='spikes'},
    gf_clamped={k:v for k,v in c[1].items() if k!='spikes'})
(ROOT/'runtime/native-validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
