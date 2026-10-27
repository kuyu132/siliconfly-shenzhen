"""K3 native brain process and procedural body. Browser only draws state."""
import json
import math
import os
import platform
import selectors
import subprocess
import threading
import time
from pathlib import Path


class Simulation:
    def __init__(self, hub, root):
        self.hub, self.root = hub, Path(root)
        self.stop_event = threading.Event()
        self.process = None
        self.thread = None
        self.status = dict(status='starting', message='加载 K3 原生神经仿真')
        self.block_gf = False

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        if self.thread: self.thread.join(timeout=3)

    def run(self):
        try:
            if platform.machine() != 'riscv64':
                raise RuntimeError('此应用必须在 K3 riscv64 上运行；不启用 Mac 代算')
            with (self.root/'runtime/brain.log').open('a') as log:
                self.process=subprocess.Popen([str(self.root/'bin/siliconfly-brain'),str(self.root/'data')],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1,
                    env={**os.environ,'OMP_WAIT_POLICY':'PASSIVE'})
                selector=selectors.DefaultSelector()
                selector.register(self.process.stdout,selectors.EVENT_READ)
                x,y,angle=.5,.5,0.
                thirst=.25
                escape_until=0
                started=time.monotonic()
                previous={}
                self.hub.log('K3 RISC-V 全连接组后端已启动')
                while not self.stop_event.is_set():
                    tick=time.monotonic()
                    state=self.hub.snapshot()
                    climate=state['controls']
                    activity=climate['activity'] if climate else .5
                    camera=state['camera']
                    drive=.8+.4*activity
                    left,right=camera.get('left',0),camera.get('right',0)
                    cmd=state['command']
                    if cmd and cmd['expires_at']>time.time(): left=right=cmd['level']
                    walking=max(0,min(1.3,(previous.get('forward_hz',0)-10)/33))
                    phase=(previous.get('sim_ms',0)/400)%1
                    # Fixed 20 x 1ms biological steps; never speed up the equation to hide slow hardware.
                    self.process.stdin.write(f'20 {drive} {left} {right} {walking} {phase} 0 {int(self.block_gf)}\n')
                    self.process.stdin.flush()
                    if not selector.select(timeout=20): raise RuntimeError('K3 神经后端 20 秒未响应')
                    line=self.process.stdout.readline()
                    if not line: raise RuntimeError('K3 神经后端退出，请查看 runtime/brain.log')
                    neural=json.loads(line)
                    dt=.020
                    if neural['gf_active']: escape_until=neural['sim_ms']+450
                    escape=neural['sim_ms']<escape_until
                    turn=max(-1,min(1,(neural['left_hz']-neural['right_hz'])*.04))
                    speed=max(0,min(1.3,(neural['forward_hz']-10)/33))*.09
                    body_state='探索' if speed>.005 else '静息'
                    if neural['groom_hz']>5 and speed<.005: body_state='梳理'
                    if escape: speed=.6;body_state='逃逸'
                    elif climate and climate['sleep'] and speed<.005: body_state='夜间静息'
                    elif neural['backward_hz']>60: speed=-.08;body_state='后退'
                    angle+=turn*dt*4
                    thirst=min(1,thirst+dt*.0007*(climate['thirst'] if climate else 1))
                    if thirst>.7 and not escape:
                        desired=math.atan2(.72-y,.75-x)
                        angle+=math.atan2(math.sin(desired-angle),math.cos(desired-angle))*dt
                    tempo=climate['tempo'] if climate else 1
                    x+=math.cos(angle)*speed*dt*tempo;y+=math.sin(angle)*speed*dt*tempo
                    if x<.08 or x>.92 or y<.12 or y>.88:
                        angle+=math.pi*.73;x=max(.08,min(.92,x));y=max(.12,min(.88,y))
                    if math.hypot(x-.75,y-.72)<.06: thirst=max(0,thirst-dt*.1)
                    elapsed=max(.001,time.monotonic()-started)
                    neural.update(x=x,y=y,angle=angle,state=body_state,thirst=thirst,
                        gait_phase=phase,escape=escape,activity_drive=drive,loom_input=max(left,right),
                        device='K3 · RISC-V CPU',realtime_factor=neural['sim_ms']/1000/elapsed,
                        gf_blocked=self.block_gf)
                    with self.hub.lock:
                        if neural['gf_events']>previous.get('gf_events',0): self.hub.log('GF 通路放电 → 逃逸动作')
                        self.hub.telemetry=neural
                        self.hub.bridge_tick=time.monotonic()
                        self.hub.history.append({k:neural[k] for k in ('loom_hz','forward_hz','population_hz','gf_active')})
                    self.status=dict(status='running',message='K3 本地 C++ · 全连接组 · 1 ms 步长')
                    previous=neural
                    self.stop_event.wait(max(0,.02-(time.monotonic()-tick)))
                selector.close()
        except Exception as e:
            if not self.stop_event.is_set():
                self.status=dict(status='error',message=str(e))
                self.hub.log('神经后端错误：'+str(e))
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
