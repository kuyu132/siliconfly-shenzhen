"""Optional K3 camera and WLED adapters. No automatic capture or port guessing."""
import glob
import colorsys
import math
import json
import os
import platform
import threading
import time
from pathlib import Path
from pose import PoseTracker, normalize_detection, SKELETON


def inventory():
    cameras = []
    for path in sorted(Path('/sys/class/video4linux').glob('video*')):
        name = (path / 'name').read_text().strip()
        # Codec M2M nodes are not cameras. Require an actual USB camera path.
        if 'usb' in str(path.resolve()).lower():
            cameras.append(dict(path='/dev/' + path.name, name=name))
    return dict(host=platform.machine(), cameras=cameras,
                serial=sorted(glob.glob('/dev/serial/by-id/*')))


class Camera:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.frame = b''
        self.state = dict(status='stopped', left=0, right=0, persons=0, message='尚未启动 K3 摄像头')

    def snapshot(self):
        with self.lock:
            s = dict(self.state)
        if time.monotonic() - s.get('tick', 0) > 1:
            s.update(left=0, right=0, actors=[], persons=0, pose_fresh=False)
        s.pop('tick', None)
        return s

    def start(self, device, model_config):
        if device not in [x['path'] for x in inventory()['cameras']]:
            raise ValueError('请选择探测到的 K3 USB 摄像头；编解码节点不可用')
        if not model_config or not Path(model_config).is_file():
            raise ValueError('尚未配置已下载的 SpaceMIT 视觉模型 YAML')
        if self.thread and self.thread.is_alive():
            raise ValueError('摄像头已在运行')
        self.stop_event.clear()
        self.device, self.config = device, model_config
        self.thread = threading.Thread(target=self.run, args=(device, model_config), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=3)
        if self.thread and self.thread.is_alive(): raise RuntimeError('摄像头仍在释放，稍后重试')

    def run(self, device, config):
        cap = None
        try:
            import cv2
            from spacemit_vision import VisionServiceNative, VisionServiceStatus
            service = VisionServiceNative.create(config, timing_enabled=True)
            if service is None: raise RuntimeError(VisionServiceNative.last_create_error())
            cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not cap.isOpened(): raise RuntimeError('USB 摄像头无法打开，检查权限或占用')
            tracker = PoseTracker()
            while not self.stop_event.is_set():
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok: raise RuntimeError('摄像头读取失败')
                result, detections = service.infer_image(frame)
                if result != VisionServiceStatus.OK: raise RuntimeError(service.last_error())
                boxes = [r for r in detections if r.score >= .55 and str(r.label) in ('0','person')]
                h, w = frame.shape[:2]
                normalized=[normalize_detection(b,w,h) for b in boxes]
                actors=tracker.update([d for d in normalized if d],started)
                left = right = 0
                for actor in actors:
                    x=(actor['box'][0]+actor['box'][2])/2
                    left=max(left,actor['approach']*(1-x))
                    right=max(right,actor['approach']*x)
                    for a,b in SKELETON:
                        p,q=actor['joints'][a],actor['joints'][b]
                        if p and q: cv2.line(frame,(int(p[0]*w),int(p[1]*h)),(int(q[0]*w),int(q[1]*h)),(110,230,190),2)
                for b in boxes:
                    cv2.rectangle(frame, (int(b.x1),int(b.y1)), (int(b.x2),int(b.y2)), (80,220,120), 2)
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY,65])
                with self.lock:
                    if ok: self.frame = encoded.tobytes()
                    self.state = dict(status='running', left=left, right=right, persons=len(boxes),
                                      actors=actors,pose_fresh=True,pose_keypoints=17,
                                      model='YOLOv8n-Pose · SpaceMIT',
                                      tick=time.monotonic(), inference_ms=round((time.monotonic()-started)*1000,1),
                                      message='K3 本地姿态 · 17 关键点 · 像素人动作跟随')
                self.stop_event.wait(max(0, .15-(time.monotonic()-started)))
        except Exception as e:
            with self.lock: self.state = dict(status='error', left=0, right=0, message=str(e))
        finally:
            if cap: cap.release()
            with self.lock:
                if self.state['status'] != 'error': self.state = dict(status='stopped', left=0, right=0, message='摄像头已停止')


class Strip:
    def __init__(self):
        self.status = dict(status='disconnected', message='灯带未连接')
        self.fd = None
        self.count = 60
        self.color = [80,180,130]
        self.lock = threading.RLock()
        self.original = None
        self.mode = 'solid'
        self.brightness = .12
        self.ambient_strength = .30
        self.auto_epoch = time.monotonic()
        self.hue_offset = .38
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                self.update()
                self.stop_event.wait(1/15)
        self.thread=threading.Thread(target=loop,daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=1)
        self.close()

    def snapshot(self):
        with self.lock:
            return dict(self.status,mode=self.mode,configured_rgb=self.color[:],brightness=self.brightness,
                        ambient_strength=self.ambient_strength,auto_period_seconds=24)

    def configure(self,payload):
        mode=payload.get('mode',self.mode)
        if mode not in ('solid','auto'): raise ValueError('灯光模式必须为 solid 或 auto')
        values={}
        for key,low,high in [('brightness',0,.15),('ambient_strength',.08,.42)]:
            value=payload.get(key,getattr(self,key))
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
                raise ValueError(f'{key} 必须在 {low}–{high} 之间')
            values[key]=value
        with self.lock:
            if mode=='auto' and self.mode!='auto':
                self.auto_epoch=time.monotonic()
                self.hue_offset=colorsys.rgb_to_hsv(*(v/255 for v in self.color))[0]
            self.mode=mode
            for key,value in values.items(): setattr(self,key,value)
            self.update()

    def output_rgb(self,now=None):
        now=time.monotonic() if now is None else now
        color=self.color
        if self.mode=='auto':
            hue=(self.hue_offset+(now-self.auto_epoch)/24)%1
            color=[round(v*255) for v in colorsys.hsv_to_rgb(hue,.72,.85)]
        return [round(c*self.brightness) for c in color]

    def set_color(self,rgb):
        if not isinstance(rgb,list) or len(rgb)!=3 or any(type(c) is not int or not 0<=c<=255 for c in rgb):
            raise ValueError('rgb 必须为三个 0–255 整数')
        with self.lock:
            self.color=rgb[:]
            self.mode='solid'
            self.update()

    def _write(self,data):
        import select
        end=time.monotonic()+.3
        while data:
            if time.monotonic()>end: raise TimeoutError('灯带写入超时')
            if not select.select([], [self.fd], [], .02)[1]: continue
            try: count=os.write(self.fd,data)
            except BlockingIOError: continue
            if count==0: raise OSError('灯带断开')
            data=data[count:]

    def _pixels(self,pixels):
        n=self.count-1
        self._write(b'Ada'+bytes((n>>8,n&255,(n>>8)^(n&255)^0x55))+bytes(pixels))

    def connect(self,path):
        with self.lock:
            if path not in inventory()['serial']: raise ValueError('请选择实际检测到的串口控制器')
            if self.fd is not None: raise ValueError('灯带已连接')
            import termios,fcntl,array,select
            self.fd=os.open(path,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
            try:
                fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.ioctl(self.fd,termios.TIOCEXCL)
                self.original=termios.tcgetattr(self.fd)
                settings=termios.tcgetattr(self.fd)
                settings[0]=settings[1]=settings[3]=0
                settings[2]=termios.CS8|termios.CREAD|termios.CLOCAL
                settings[4]=settings[5]=termios.B115200
                settings[6][termios.VMIN]=settings[6][termios.VTIME]=0
                termios.tcsetattr(self.fd,termios.TCSANOW,settings)
                fcntl.ioctl(self.fd,termios.TIOCMBIS,array.array('i',[termios.TIOCM_DTR]))
                termios.tcflush(self.fd,termios.TCIFLUSH)
                self._write(b'{"v":true}\n')
                buffer=b'';end=time.monotonic()+3
                while time.monotonic()<end:
                    if not select.select([self.fd],[],[],.1)[0]: continue
                    buffer+=os.read(self.fd,65536)
                    while b'\n' in buffer:
                        line,_,buffer=buffer.partition(b'\n')
                        try: info=json.loads(line)
                        except ValueError: continue
                        if 'info' not in info: continue
                        count=info['info']['leds']['count']
                        if not 1<=count<=300: raise ValueError('不支持的灯珠数量')
                        if info['info'].get('live') or info['state'].get('lor',0):
                            raise ValueError('灯带正被其他实时源控制')
                        self.count=count
                        self.status=dict(status='connected',message=f'WLED {count} 灯 · 15% 输出上限',
                            path=path,count=count,version=info['info']['ver'],configured_rgb=self.color[:])
                        self._pixels([0]*(count*3))
                        return
                raise TimeoutError('WLED 未回应，未确认灯带连接')
            except Exception:
                self.close()
                raise

    def update(self):
        with self.lock:
            if self.fd is None: return
            try:
                # One K3 clock drives both physical LEDs and the published page color.
                output=self.output_rgb()
                self._pixels(output*self.count)
                self.status.update(configured_rgb=self.color[:],sent_rgb=output,last_sent_at=time.time())
            except Exception as e:
                self.close()
                self.status=dict(status='error',message=str(e))

    def close(self):
        with self.lock:
            if self.fd is not None:
                import termios,fcntl
                try:
                    self._pixels([0]*(self.count*3))
                    if self.original: termios.tcsetattr(self.fd,termios.TCSANOW,self.original)
                except Exception: pass
                try: fcntl.ioctl(self.fd,termios.TIOCNXCL)
                except Exception: pass
                os.close(self.fd)
                self.fd=None
            self.status=dict(status='disconnected',message='灯带已断开')
