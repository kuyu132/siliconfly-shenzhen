"""Frame-local COCO pose normalization and short-lived geometric tracking on K3.

IDs are temporary scene tracks, never identities. No missing joint hallucination.
"""
import math

SKELETON=((5,6),(5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16))
MIN_SCORE=.35

def clamp(x,lo=0,hi=1): return max(lo,min(hi,x))

def gesture(joints):
    def pt(i):
        p=joints[i] if i<len(joints) else None
        return p if p and p[2]>=MIN_SCORE else None
    ls,rs,lw,rw=map(pt,(5,6,9,10))
    if not(ls and rs): return '关键点不完整'
    left=lw is not None and lw[1]<ls[1]-.04
    right=rw is not None and rw[1]<rs[1]-.04
    if left and right: return '双手举起'
    if left: return '左手举起'
    if right: return '右手举起'
    if lw and rw and abs(lw[0]-rw[0])>abs(ls[0]-rs[0])*1.7: return '手臂展开'
    return '姿态跟随' if sum(pt(i) is not None for i in range(17))>=9 else '上身跟随'

def normalize_detection(result,width,height):
    raw=(result.x1/width,result.y1/height,result.x2/width,result.y2/height)
    if not all(math.isfinite(x) for x in raw): return None
    box=[clamp(x) for x in raw]
    if box[2]-box[0]<.015 or box[3]-box[1]<.035: return None
    joints=[]
    for kp in list(result.keypoints)[:17]:
        x,y,score=float(kp.x)/width,float(kp.y)/height,float(kp.visibility)
        if not all(math.isfinite(v) for v in (x,y,score)) or not(0<=x<=1 and 0<=y<=1) or score<MIN_SCORE:
            joints.append(None)
        else: joints.append([x,y,clamp(score)])
    joints.extend([None]*(17-len(joints)))
    return dict(box=box,joints=joints,score=round(float(result.score),3))

def overlap(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=lambda c:(c[2]-c[0])*(c[3]-c[1])
    return intersection/max(1e-8,area(a)+area(b)-intersection)

class PoseTracker:
    def __init__(self):
        self.tracks={}
        self.next_id=1

    def update(self,detections,now):
        self.tracks={i:t for i,t in self.tracks.items() if now-t['tick']<.7}
        used=set();actors=[]
        # Largest six receive avatars; UI retains the full detection count.
        for d in sorted(detections,key=lambda d:(d['box'][2]-d['box'][0])*(d['box'][3]-d['box'][1]),reverse=True)[:6]:
            candidates=[(overlap(d['box'],t['box']),i) for i,t in self.tracks.items() if i not in used]
            match=max(candidates,default=(0,None))
            i=match[1] if match[0]>.25 else self.next_id
            old=self.tracks.get(i)
            if old is None: self.next_id+=1
            used.add(i)
            # Smooth measured joints only. A missing measurement stays missing.
            joints=d['joints']
            if old and now-old['tick']<.5:
                joints=[([p[0]*.65+q[0]*.35,p[1]*.65+q[1]*.35,p[2]] if p and q else p)
                        for p,q in zip(joints,old['joints'])]
            box=d['box'];area=(box[2]-box[0])*(box[3]-box[1]);strength=0
            if old and .02<now-old['tick']<.5:
                strength=clamp((math.sqrt(area)-math.sqrt(old['area']))/(now-old['tick'])*3)
            cx=(box[0]+box[2])/2
            actor=dict(id=i,box=box,joints=joints,score=d['score'],action=gesture(joints),
                visible_joints=sum(p is not None for p in joints),
                scene_x=clamp(1-cx,.09,.91),scene_y=clamp(.50+math.sqrt(area)*.36,.52,.82),
                scene_height=clamp((box[3]-box[1])*.50,.14,.40),approach=strength)
            self.tracks[i]=dict(box=box,joints=joints,tick=now,area=area)
            actors.append(actor)
        return actors
