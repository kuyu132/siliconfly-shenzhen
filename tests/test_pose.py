import unittest
from types import SimpleNamespace
from pose import normalize_detection,gesture,PoseTracker

def person(x=.3):
    j=[None]*17
    for i,p in {0:(x,.1),5:(x-.04,.2),6:(x+.04,.2),7:(x-.08,.3),8:(x+.08,.3),
                9:(x-.08,.4),10:(x+.08,.4),11:(x-.03,.4),12:(x+.03,.4),
                13:(x-.03,.55),14:(x+.03,.55),15:(x-.03,.7),16:(x+.03,.7)}.items():j[i]=[*p,.9]
    return dict(box=[x-.12,.05,x+.12,.75],joints=j,score=.9)

class PoseTests(unittest.TestCase):
    def test_low_confidence_and_invalid_points_are_missing(self):
        kp=[SimpleNamespace(x=40,y=40,visibility=.1),SimpleNamespace(x=float('nan'),y=40,visibility=.9),SimpleNamespace(x=50,y=50,visibility=.9)]
        d=normalize_detection(SimpleNamespace(x1=0,y1=0,x2=100,y2=100,keypoints=kp,score=.8),100,100)
        self.assertEqual(len(d['joints']),17)
        self.assertEqual(d['joints'][:3],[None,None,[.5,.5,.9]])

    def test_gestures_require_measured_wrists(self):
        p=person();p['joints'][9]=[.2,.05,.9];p['joints'][10]=[.4,.05,.9]
        self.assertEqual(gesture(p['joints']),'双手举起')
        p['joints'][10]=None
        self.assertEqual(gesture(p['joints']),'左手举起')
        self.assertEqual(gesture([None]*17),'关键点不完整')

    def test_tracking_survives_detection_reorder(self):
        tracker=PoseTracker();a=tracker.update([person(.2),person(.7)],1)
        b=tracker.update([person(.71),person(.21)],1.2)
        self.assertEqual({round(x['scene_x'],1):x['id'] for x in a},{round(x['scene_x'],1):x['id'] for x in b})

    def test_missing_and_expired_people_disappear(self):
        tracker=PoseTracker();old=tracker.update([person()],1)[0]['id']
        self.assertEqual(tracker.update([],1.1),[])
        self.assertNotEqual(tracker.update([person()],2)[0]['id'],old)

    def test_missing_joint_is_not_carried_over(self):
        tracker=PoseTracker();tracker.update([person()],1)
        p=person();p['joints'][9]=None
        self.assertIsNone(tracker.update([p],1.1)[0]['joints'][9])

    def test_growth_and_new_track(self):
        tracker=PoseTracker();a=tracker.update([person()],1)
        self.assertEqual(a[0]['approach'],0)
        p=person();p['box']=[.1,0,.5,.9]
        self.assertGreater(tracker.update([p],1.2)[0]['approach'],0)

if __name__=='__main__': unittest.main()
