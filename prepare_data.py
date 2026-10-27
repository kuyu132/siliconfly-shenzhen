"""Verify original FlyWire binaries and generate native layout + display sample."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def prepare():
    data = ROOT/'data'
    m = json.loads((data/'connectome.json').read_text())
    for name, spec in m['files'].items():
        raw = (data/name).read_bytes()
        assert len(raw) == spec['bytes'] and hashlib.sha256(raw).hexdigest() == spec['sha256'], name
    header = ['#pragma once', f'constexpr unsigned N={m["neuronCount"]}, E={m["edgeCount"]};']
    for name, a in m['arrays'].items():
        header.append(f'constexpr unsigned OFF_{name}={a["byteOffset"]};')
    (ROOT/'native').mkdir(exist_ok=True)
    (ROOT/'native/layout.hpp').write_text('\n'.join(header)+'\n')
    raw = (data/'neurons.bin').read_bytes()
    points = []
    for i in range(0, m['neuronCount'], 45):
        p = struct.unpack_from('<fff', raw, m['arrays']['pos']['byteOffset']+i*12)
        points.append([i, *[round(v, 3) for v in p]])
    (ROOT/'web').mkdir(exist_ok=True)
    (ROOT/'web/points.json').write_text(json.dumps(points, separators=(',', ':')))
    print(f'Verified {m["neuronCount"]} neurons, {m["edgeCount"]} edges')

if __name__ == '__main__': prepare()
