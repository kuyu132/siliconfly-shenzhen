import unittest
from hardware import Strip,Camera

class LightTests(unittest.TestCase):
    def test_single_color_and_black(self):
        s=Strip();s.set_color([255,0,0])
        self.assertEqual(s.output_rgb(0),[31,0,0])
        self.assertEqual(s.output_rgb(99999),[31,0,0])
        s.set_color([0,0,0]);self.assertEqual(s.output_rgb(),[0,0,0])

    def test_auto_changes_on_board_clock_and_loops(self):
        s=Strip();s.configure({'mode':'auto'});epoch=s.auto_epoch
        self.assertNotEqual(s.output_rgb(epoch),s.output_rgb(epoch+8))
        self.assertEqual(s.output_rgb(epoch),s.output_rgb(epoch+24))
        s.set_color([10,20,30]);self.assertEqual(s.mode,'solid')

    def test_brightness_caps_and_invalid_settings(self):
        s=Strip();s.configure({'brightness':.15});s.set_color([255,255,255])
        self.assertEqual(s.output_rgb(),[38,38,38])
        for bad in ({'brightness':.16},{'brightness':float('nan')},{'ambient_strength':.8},{'mode':'bad'}):
            with self.assertRaises(ValueError):s.configure(bad)
        s.configure({'brightness':0});self.assertEqual(s.output_rgb(),[0,0,0])

    def test_page_snapshot_uses_exact_sent_frame(self):
        s=Strip();s.fd=999  # Mock frame sink, no real serial port is touched.
        frames=[];s._pixels=lambda p:frames.append(p)
        s.count=30;s.status={'status':'connected'};s.set_color([0,20,255])
        self.assertEqual(frames[-1][:3],s.snapshot()['sent_rgb'])
        self.assertEqual(len(frames[-1]),90)
        self.assertNotIn('ambient_rgb',Camera().snapshot())

    def test_stale_pose_disappears(self):
        c=Camera();c.state=dict(status='running',tick=0,persons=1,actors=[{'id':1}],pose_fresh=True,left=1,right=1)
        state=c.snapshot()
        self.assertFalse(state['pose_fresh'])
        self.assertEqual(state['actors'],[])

if __name__=='__main__':unittest.main()
