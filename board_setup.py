"""Prepare an isolated K3 environment using installed RISC-V native wheels."""
import hashlib
import json
import platform
import shutil
import subprocess
import sysconfig
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
assert platform.machine()=='riscv64', 'Run setup on K3'
subprocess.run(['python3','-m','venv','--system-site-packages',str(ROOT/'.venv')],check=True)
source=Path('/home/bianbu/workshop-deploy/k3-workshop-packages/workshop-rgb-light/.venv/lib/python3.14/site-packages')
target=ROOT/'.venv/lib/python3.14/site-packages'
# Copy only runtime modules, never change the source environment or Gateway.
for pattern in ('cv2','opencv_python*','spacemit_vision*','onnxruntime*','numpy','numpy.libs','numpy-*.dist-info'):
    for item in source.glob(pattern):
        dest=target/item.name
        if item.is_dir(): shutil.copytree(item,dest,dirs_exist_ok=True)
        else: shutil.copy2(item,dest)
(ROOT/'models').mkdir(exist_ok=True)
model=ROOT/'models/yolov8n_no_dfl.q.onnx'
url='https://archive.spacemit.com/spacemit-ai/model_zoo/vision/yolov8/yolov8n_no_dfl.q.onnx'
if not model.exists():
    with urllib.request.urlopen(url,timeout=30) as response:
        data=response.read()
    if len(data)!=3367042 or hashlib.md5(data).hexdigest()!='434b4a1d6e9567c46d28030d47c17445':
        raise ValueError('Official model checksum mismatch')
    model.write_bytes(data)
(ROOT/'models/source.json').write_text(json.dumps(dict(url=url,bytes=model.stat().st_size,
    sha256=hashlib.sha256(model.read_bytes()).hexdigest()),indent=2))
(ROOT/'models/coco.txt').write_text('person\n'+'\n'.join(f'class-{i}' for i in range(1,80))+'\n')
(ROOT/'models/person.yaml').write_text(f'''model_path: {model}
label_file_path: {ROOT/'models/coco.txt'}
image_size: [640, 640]
class: deploy.yolov8.YOLOv8Detector
default_params:
  conf_threshold: 0.5
  iou_threshold: 0.45
  num_threads: 2
  providers:
    - SpaceMITExecutionProvider
''')
print('K3 environment + official YOLOv8n ready')
