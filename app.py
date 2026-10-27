#!/usr/bin/env python3
"""K3 observatory: all computation runs on riscv64, browser renders only."""
import argparse
import copy
import json
import math
import mimetypes
import os
import platform
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from climate import PRESETS, SHANGHAI, controls, fetch_weather, validated
from hardware import Camera, Strip, inventory
from simulation import Simulation

ROOT = Path(__file__).resolve().parent


class Observatory:
    def __init__(self, runtime=None):
        self.lock = threading.RLock()
        self.runtime = Path(runtime or ROOT/'runtime')
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.mode = 'live'
        self.weather = None
        self.weather_error = '正在获取深圳天气'
        self.weather_busy = False
        self.telemetry = {}
        self.bridge_tick = 0
        self.simulation = Simulation(self, ROOT)
        self.command_id = 0
        self.command = None
        self.events = deque(maxlen=24)
        self.history = deque(maxlen=160)
        self.camera = Camera()
        self.strip = Strip()
        self.ai = dict(status='idle', text='', model='qwen3-0.6b-q4_0')
        self.hardware = inventory()
        self.log('观测站已启动，等待神经仿真连接')

    def log(self, message):
        with self.lock:
            self.events.appendleft(dict(time=datetime.now(SHANGHAI).strftime('%H:%M:%S'), message=message))

    def effective(self):
        if self.mode in PRESETS:
            return dict(PRESETS[self.mode], source='季节实验 · 人工设定', observed_at=None)
        if self.mode == 'manual': return dict(self.manual)
        if not self.weather: return None
        w = dict(self.weather)
        now = datetime.now(SHANGHAI)
        w['hour'] = now.hour + now.minute/60 + now.second/3600
        w['month'] = now.month
        return w

    def snapshot(self):
        with self.lock:
            w = self.effective()
            is_live = self.mode == 'live'
            age = None
            if is_live and w:
                age = (datetime.now(SHANGHAI)-datetime.fromisoformat(w['observed_at'])).total_seconds()
                # Do not apply yesterday's sun times or old weather as current.
                if age > 7200: w = None
            connected = time.monotonic()-self.bridge_tick < 3
            return copy.deepcopy(dict(
                time=datetime.now(SHANGHAI).isoformat(), mode=self.mode, weather=w,
                weather_status='unavailable' if w is None else ('cached' if is_live and self.weather_error else 'current' if is_live else 'experiment'),
                weather_error=self.weather_error if is_live else '', weather_age_seconds=age,
                weather_busy=self.weather_busy,
                controls=controls(w) if w else None, bridge_connected=connected,
                telemetry=self.telemetry if connected else {}, history=list(self.history),
                events=list(self.events), camera=self.camera.snapshot(), strip=self.strip.snapshot(),
                hardware=self.hardware, ai=self.ai, command=self.command,
                architecture=dict(hub=platform.machine(), brain='K3 / RISC-V / C++', simulation=self.simulation.status, city='深圳', timezone='Asia/Shanghai'),
                presets=PRESETS))

    def refresh(self):
        with self.lock:
            if self.weather_busy: return
            self.weather_busy = True
        def run():
            try:
                w = fetch_weather()
                with self.lock:
                    self.weather, self.weather_error = w, ''
                (self.runtime/'weather-latest.json').write_text(json.dumps(w, ensure_ascii=False, indent=2))
                self.log('深圳天气已更新 · Open-Meteo 天气模型')
            except Exception as e:
                with self.lock: self.weather_error = str(e)
                self.log('天气更新失败；保留来源状态，可切换季节实验')
            finally:
                with self.lock: self.weather_busy = False
        threading.Thread(target=run, daemon=True).start()

    def set_mode(self, payload):
        mode = payload.get('mode')
        if mode not in {*PRESETS, 'live', 'manual'}: raise ValueError('未知场景')
        if mode == 'manual':
            w = validated(payload.get('weather', {}))
            w.update(label='自定义气候实验', source='人工设定 · 非当前天气', observed_at=None)
        with self.lock:
            if mode == 'manual': self.manual = w
            self.mode = mode
        self.log('切换场景：'+(PRESETS[mode]['label'] if mode in PRESETS else mode))
        if mode == 'live': self.refresh()

    def stimulate(self, payload):
        level = payload.get('level', 0.9)
        if isinstance(level, bool) or not isinstance(level, (int,float)) or not math.isfinite(level) or not 0 <= level <= 1:
            raise ValueError('刺激强度必须为 0–1')
        with self.lock:
            self.command_id += 1
            self.command = dict(id=self.command_id, level=level, expires_at=time.time()+2)
        self.log('人工刺激输入：'+str(level)+'（非摄像头检测）')

    def explain(self):
        snapshot=self.snapshot()
        if not snapshot['weather']: raise ValueError('先取得天气或选择一个季节实验')
        with self.lock:
            if self.ai['status']=='running': raise ValueError('K3 正在解读，请稍候')
            self.ai=dict(status='running', text='', model='qwen3-0.6b-q4_0')
        def run():
            started=time.monotonic()
            camera_running=self.camera.thread is not None and self.camera.thread.is_alive()
            try:
                if camera_running: self.camera.stop()
                from gateway_client import GatewayClient
                client=GatewayClient(os.environ.get('K3_GATEWAY','http://127.0.0.1:18790'), timeout=90)
                text=json.dumps(dict(weather={k:snapshot['weather'].get(k) for k in ('label','source','temperature','humidity','rain','weather_code')},
                    effects=snapshot['controls']['explanation'], neural_connected=snapshot['bridge_connected'],
                    telemetry={k:snapshot['telemetry'].get(k) for k in ('state','loom_hz','forward_hz','gf_active','gf_blocked')}),ensure_ascii=False)
                with client.session('llm','qwen3-0.6b-q4_0'):
                    answer=client.chat(text[:1500], max_tokens=220,
                        system='你是果蝇观测站讲解员。仅根据给定气象、简化生态规则和遥测，用中文三句话解释当前场景。不要输出日期、时刻、未提供的测量。只复述给出的生态规则和身体状态，不得从状态反推气候原因。最后一句须说明生态参数为演示假设。人工实验不能称为真实天气。连接组仿真不能称为生命复活或意识。不要虚构测量或因果验证。生态参数是演示假设。/no_think')
                    request_id=client.last_request_id
                import re
                answer=re.sub(r'<think>.*?</think>','',answer,flags=re.S).strip()
                if not answer: raise ValueError('模型未输出有效解释')
                with self.lock:
                    self.ai=dict(status='ready',text=answer,model='qwen3-0.6b-q4_0',
                                 elapsed_ms=round((time.monotonic()-started)*1000),
                                 request_id=request_id,
                                 context_label=snapshot['weather']['label'], generated_at=datetime.now(SHANGHAI).isoformat())
                self.log('K3 本地模型解读完成')
            except Exception as e:
                with self.lock: self.ai=dict(status='error',text=str(e),model='qwen3-0.6b-q4_0')
            finally:
                if camera_running:
                    try: self.camera.start(self.camera.device,self.camera.config)
                    except Exception as e: self.log('视觉恢复失败：'+str(e))
        threading.Thread(target=run,daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version='SiliconFly/1.0'
    def log_message(self, *_): pass

    def send(self, code, data, content_type='application/json; charset=utf-8'):
        if not isinstance(data,bytes): data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError): pass

    def do_GET(self):
        path=urlparse(self.path).path
        hub=self.server.hub
        if path=='/healthz': return self.send(200,dict(ok=True,service='siliconfly-shenzhen',
            architecture=platform.machine(),simulation=hub.simulation.status,ai_verified=hub.ai['status']=='ready'))
        if path=='/api/state': return self.send(200,hub.snapshot())
        if path=='/favicon.ico': return self.send(204,b'','image/x-icon')
        if path=='/api/camera.jpg':
            data=hub.camera.frame
            return self.send(200,data,'image/jpeg') if data else self.send(404,dict(error='尚无真实画面'))
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/points.json':'points.json'}
        if path in files:
            file=ROOT/'web'/files[path]
            return self.send(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'text/plain')
        self.send(404,dict(error='not found'))

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'): return self.send(403,dict(error='拒绝跨站操作'))
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=4500000: raise ValueError('请求体大小无效')
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict): raise ValueError('请求体必须为 JSON 对象')
            hub=self.server.hub
            path=urlparse(self.path).path
            if path=='/api/mode': hub.set_mode(payload)
            elif path=='/api/stimulus': hub.stimulate(payload)
            elif path=='/api/gf':
                if not isinstance(payload.get('blocked'),bool): raise ValueError('blocked 必须为布尔值')
                hub.simulation.block_gf=payload['blocked']
                hub.log('GF 神经元钳制：'+str(payload['blocked']))
            elif path=='/api/strip/color': hub.strip.set_color(payload.get('rgb'))
            elif path=='/api/strip/settings': hub.strip.configure(payload)
            elif path=='/api/weather/refresh': hub.refresh()
            elif path=='/api/explain': hub.explain()
            elif path=='/api/hardware/refresh': hub.hardware=inventory()
            elif path=='/api/camera/start':
                if hub.ai['status']=='running': raise ValueError('等待本地讲解结束后再开启摄像头')
                hub.camera.start(payload.get('device'),os.environ.get('K3_VISION_CONFIG',str(ROOT/'models/person-pose.yaml')))
            elif path=='/api/camera/stop': hub.camera.stop()
            elif path=='/api/strip/connect': hub.strip.connect(payload.get('device'))
            elif path=='/api/strip/disconnect': hub.strip.close()
            else: return self.send(404,dict(error='not found'))
            self.send(200,dict(ok=True))
        except (ValueError,KeyError,TypeError) as e: self.send(400,dict(error=str(e)))
        except Exception as e: self.send(500,dict(error=str(e)))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--port',type=int,default=int(os.environ.get('K3_APP_PORT','8330')))
    parser.add_argument('--no-weather',action='store_true')
    args=parser.parse_args()
    hub=Observatory()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    server.hub=hub
    hub.simulation.start()
    hub.strip.start()
    if not args.no_weather:
        def weather_loop():
            while True:
                hub.refresh()
                time.sleep(600)
        threading.Thread(target=weather_loop,daemon=True).start()
    print(f'SiliconFly Shenzhen: http://{args.host}:{args.port}',flush=True)
    import signal
    def shutdown(*_):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        hub.simulation.stop()
        hub.camera.stop()
        hub.strip.stop()
        server.server_close()


if __name__=='__main__': main()
