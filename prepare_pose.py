"""Download the verified official RISC-V pose model to this K3 project."""
import hashlib
import json
import platform
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent
assert platform.machine()=='riscv64', 'Run on K3'
folder=ROOT/'models'
folder.mkdir(exist_ok=True)
model=folder/'yolov8n-pose.q.onnx'
url='https://archive.spacemit.com/spacemit-ai/model_zoo/vision/yolov8_pose/yolov8n-pose.q.onnx'
if not model.exists():
    with urlopen(url,timeout=30) as r: data=r.read()
else: data=model.read_bytes()
assert len(data)==3797711 and hashlib.md5(data).hexdigest()=='29682aecea1d21c7191d7de1f1c3cc62', 'Model checksum mismatch'
model.write_bytes(data)
(folder/'pose-source.json').write_text(json.dumps(dict(url=url,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()),indent=2))
(folder/'person-pose.yaml').write_text(f'''model_path: {model}
label_file_path: {folder/'coco.txt'}
image_size: [640, 640]
class: deploy.yolov8_pose.YOLOv8PoseDetector
default_params:
  conf_threshold: 0.5
  iou_threshold: 0.45
  num_threads: 2
  providers:
    - SpaceMITExecutionProvider
''')
print('Official YOLOv8n-Pose ready, 17 COCO keypoints')
