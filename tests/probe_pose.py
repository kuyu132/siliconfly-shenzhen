"""Run on K3 only while the app camera is stopped. Saves numerical evidence."""
import json
import time
from pathlib import Path
import cv2
from spacemit_vision import VisionServiceNative,VisionServiceStatus

root=Path(__file__).resolve().parents[1]
s=VisionServiceNative.create(str(root/'models/person-pose.yaml'),timing_enabled=True)
c=cv2.VideoCapture('/dev/video1',cv2.CAP_V4L2)
try:
    c.set(cv2.CAP_PROP_FRAME_WIDTH,640);c.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
    rows=[]
    for _ in range(5):
        ok,frame=c.read()
        assert ok,'Camera read'
        t=time.monotonic();status,people=s.infer_image(frame)
        assert status==VisionServiceStatus.OK,status
        rows.append(dict(ms=round((time.monotonic()-t)*1000,1),people=[dict(label=str(p.label),score=p.score,
            box=[p.x1,p.y1,p.x2,p.y2],joints=[[k.x,k.y,k.visibility] for k in p.keypoints]) for p in people]))
    (root/'runtime/pose-probe.json').write_text(json.dumps(rows,indent=2))
    print(json.dumps(rows[-1]))
finally:c.release()
