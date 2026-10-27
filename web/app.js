'use strict';
const $=id=>document.getElementById(id);
let state=null,points=[],lastGood=0,toastTimer,renderFly={x:.5,y:.5,angle:0},renderStrip=[0,0,0],lastGlow=0;
const fmt=(x,d=1)=>Number.isFinite(x)?x.toFixed(d):'—';
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,7000)}
async function post(path,body={}){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||r.statusText);return data}
function action(id,fn){$(id).addEventListener('click',async()=>{const b=$(id);b.disabled=true;try{await fn()}catch(e){toast(e.message)}finally{b.disabled=false}})}
action('refresh',()=>post('weather/refresh'));
action('stimulate',async()=>{await post('stimulus',{level:.95});toast('已输入人工靠近刺激，观察 LC4 / LPLC2 → GF 回路')});
action('explain',()=>post('explain'));
action('fullscreen',async()=>{
  if(document.fullscreenElement) return document.exitFullscreen();
  if(!document.documentElement.requestFullscreen) {toast('当前浏览器不支持全屏接口；场景已铺满窗口，可使用浏览器全屏功能');return}
  try{await document.documentElement.requestFullscreen()}catch{toast('浏览器限制了全屏，请在独立浏览器打开此页面并点击全屏')}
});
document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'⛶ 退出全屏':'⛶ 进入全屏'});
for(const selector of ['.inputs','.weather','.brain-panel','.insight']) $('controlCards').append(document.querySelector(selector));
function setControls(open){$('controlsPanel').hidden=!open;$('controlsToggle').setAttribute('aria-expanded',String(open));if(open)$('closeControls').focus();else $('controlsToggle').focus()}
action('controlsToggle',()=>setControls($('controlsPanel').hidden));
action('closeControls',()=>setControls(false));
document.addEventListener('keydown',e=>{
  if(/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)||e.repeat)return;
  if(e.key.toLowerCase()==='f'){$('fullscreen').click();e.preventDefault()}
  if(e.key.toLowerCase()==='c'){setControls($('controlsPanel').hidden);e.preventDefault()}
  if(e.key==='Escape'&&!$('controlsPanel').hidden)setControls(false);
});
$('mode').addEventListener('change',async e=>{try{await post('mode',{mode:e.target.value})}catch(err){toast(err.message)}});
$('blockGF').addEventListener('change',async e=>{try{await post('gf',{blocked:e.target.checked})}catch(err){toast(err.message);e.target.checked=!e.target.checked}});
for(const id of ['stripColor','quickColor'])$(id).addEventListener('change',async e=>{try{const v=e.target.value;await post('strip/color',{rgb:[1,3,5].map(i=>parseInt(v.slice(i,i+2),16))})}catch(err){toast(err.message)}});
action('solidQuick',()=>post('strip/settings',{mode:'solid'}));
action('autoQuick',()=>post('strip/settings',{mode:'auto'}));
$('lightMode').addEventListener('change',async e=>{try{await post('strip/settings',{mode:e.target.value})}catch(err){toast(err.message)}});
for(const [id,key]of [['stripBrightness','brightness'],['ambientStrength','ambient_strength']]){
  $(id).addEventListener('input',e=>$(id==='stripBrightness'?'brightnessValue':'ambientValue').textContent=e.target.value+'%');
  $(id).addEventListener('change',async e=>{try{await post('strip/settings',{[key]:Number(e.target.value)/100})}catch(err){toast(err.message)}});
}
action('cameraToggle',()=>{if(!state)throw Error('尚未连接 K3');if(state.camera.status==='running')return post('camera/stop');const device=state.hardware.cameras[0]?.path;if(!device)throw Error('K3 未检测到 USB 摄像头');return post('camera/start',{device})});
action('stripToggle',()=>{if(!state)throw Error('尚未连接 K3');if(state.strip.status==='connected')return post('strip/disconnect');const device=state.hardware.serial[0];if(!device)throw Error('K3 未检测到串口灯带');return post('strip/connect',{device})});
async function poll(){try{const r=await fetch('/api/state');if(!r.ok)throw Error('服务无响应');state=await r.json();lastGood=performance.now();update()}catch(e){document.body.classList.add('offline');$('connection').textContent='K3 连接中断';$('state').textContent='数据已暂停'}finally{setTimeout(poll,180)}}
function update(){
  const s=state,t=s.telemetry,w=s.weather,c=s.camera;document.body.classList.toggle('offline',!s.bridge_connected);
  $('connection').textContent=s.bridge_connected?'K3 原生运行中':'神经后端未连接';
  $('clock').textContent=new Date(s.time).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
  $('state').textContent=s.bridge_connected?t.state:'后端离线';
  $('loom').innerHTML=fmt(t.loom_hz)+' <em>Hz</em>';$('forward').innerHTML=fmt(t.forward_hz)+' <em>Hz</em>';
  $('gf').textContent=t.gf_blocked?'已钳制':t.gf_active?'正在放电':Number.isFinite(t.gf_events)?`${t.gf_events} 次放电`:'—';
  $('rtf').innerHTML=fmt(t.realtime_factor,2)+' <em>×</em>';
  $('flyCaption').textContent=s.bridge_connected?`${t.state} · 生物仿真时钟 ${fmt(t.sim_ms/1000,1)} s`:s.architecture.simulation.message;
  $('backend').textContent=`${s.architecture.hub} · ${fmt(t.step_us/1000,2)} ms / 步`;
  $('mode').value=s.mode;$('blockGF').checked=!!t.gf_blocked;
  $('sceneLabel').textContent=w?.label||'深圳 · 天气不可用';
  $('sceneSource').textContent=w?.source||s.weather_error;
  $('temp').textContent=fmt(w?.temperature);$('humidity').textContent=fmt(w?.humidity,0)+' %';$('rain').textContent=fmt(w?.rain)+' mm';$('wind').textContent=fmt(w?.wind)+' km/h';
  $('hour').textContent=w?`${String(Math.floor(w.hour)).padStart(2,'0')}:${String(Math.floor(w.hour%1*60)).padStart(2,'0')}`:'—';
  $('weatherLabel').textContent=s.weather_status==='experiment'?'人工气候实验':s.weather_status==='current'?'天气模型当前值':s.weather_status==='cached'?'缓存数据':'天气暂不可用';
  $('weatherTime').textContent=w?.observed_at?new Date(w.observed_at).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'})+' 更新':w?'场景预设 · 非实测':'可切换季节实验';
  $('effects').replaceChildren(...(s.controls?.explanation||['实时天气不可用，神经仿真采用标记的中性驱动。']).map(text=>{const p=document.createElement('div');p.textContent='· '+text;return p}));
  const running=c.status==='running';$('camera').hidden=!running;$('cameraEmpty').hidden=running;
  $('cameraEmpty').textContent=c.status==='error'?'摄像头错误':'摄像头未启动';
  $('cameraStatus').textContent=running?`${c.model} · ${fmt(c.inference_ms,0)} ms`:c.message;
  $('persons').textContent=running?`检测到 ${c.persons} 人 · 靠近 ${fmt(Math.max(c.left,c.right),2)}`:'人体感知';
  const actors=c.pose_fresh?(c.actors||[]):[];
  $('poseCount').textContent=actors.length?`${c.persons} 位访客 · ${actors.length} 个像素化身`:running?'等待访客进入':'姿态感知未启动';
  $('poseHint').textContent=actors.length?actors.map(a=>`#${a.id} ${a.action}`).join(' · '):running?'面向摄像头，举手、展开双臂，看看场景里的自己':'打开“观测控制”启动 K3 摄像头';
  $('stageWeather').textContent=w?`${w.label} · ${fmt(w.temperature)}°C · 湿度 ${fmt(w.humidity,0)}%`:'深圳天气不可用 · 可切换季节实验';
  $('cameraToggle').textContent=running?'停止摄像头':'启动摄像头';
  $('cameraToggle').disabled=s.ai.status==='running';
  if(running && !$('controlsPanel').hidden && !$('camera').dataset.loading){$('camera').dataset.loading='1';$('camera').src='/api/camera.jpg?t='+Date.now()}
  const rgb=s.strip.status==='connected'?s.strip.sent_rgb:null;
  $('ambientColor').textContent=rgb?`RGB ${rgb.join(' / ')}`:'灯带未连接';
  const peak=rgb?Math.max(...rgb):0,chip=peak?`rgb(${rgb.map(v=>Math.round(v/peak*220))})`:'#47574a';
  $('ambientDot').style.background=$('stripLiveDot').style.background=chip;
  $('lightModeLabel').textContent=s.strip.mode==='auto'?'自动变色':'单色';
  $('lightStatus').textContent=rgb?`输出 ${rgb.join(' / ')} · 边缘柔光`:'未连接灯带 · 打开观测控制连接';
  $('solidQuick').setAttribute('aria-pressed',String(s.strip.mode==='solid'));
  $('autoQuick').setAttribute('aria-pressed',String(s.strip.mode==='auto'));
  $('lightMode').value=s.strip.mode||'solid';
  for(const id of ['stripColor','quickColor']){
    $(id).disabled=s.strip.mode==='auto';
    if(document.activeElement!==$(id)&&s.strip.configured_rgb)$(id).value='#'+s.strip.configured_rgb.map(v=>v.toString(16).padStart(2,'0')).join('');
  }
  for(const [id,key,out]of [['stripBrightness','brightness','brightnessValue'],['ambientStrength','ambient_strength','ambientValue']]){
    if(document.activeElement!==$(id)){$(id).value=Math.round((s.strip[key]||0)*100);$(out).textContent=$(id).value+'%'}
  }
  $('stripToggle').textContent=s.strip.status==='connected'?'断开灯带':'连接灯带';
  $('stripStatus').textContent=s.strip.message+(s.strip.sent_rgb?' · 发送 RGB '+s.strip.sent_rgb.join('/'):'');
  $('explain').disabled=s.ai.status==='running';$('explain').textContent=s.ai.status==='running'?'K3 正在解读…':'解读当前观测 ↗';
  if(s.ai.text)$('aiText').textContent=s.ai.text;
  $('aiMeta').textContent=s.ai.status==='ready'?`${s.ai.context_label} · ${fmt(s.ai.elapsed_ms/1000)} s · AI 生成，以观测数据为准`:'运行讲解时，视觉推理将暂时暂停。';
  $('events').replaceChildren(...s.events.slice(0,4).map(e=>{const row=document.createElement('div'),time=document.createElement('time');time.textContent=e.time;row.append(time,document.createTextNode(e.message));return row}));
}
$('camera').onload=$('camera').onerror=()=>delete $('camera').dataset.loading;
function context(id){const canvas=$(id),dpr=Math.min(devicePixelRatio,2),w=canvas.clientWidth,h=canvas.clientHeight;if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr)}const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);return[ctx,w,h]}
function ellipse(g,x,y,rx,ry,angle,fill,stroke){g.beginPath();g.ellipse(x,y,rx,ry,angle,0,Math.PI*2);if(fill){g.fillStyle=fill;g.fill()}if(stroke){g.strokeStyle=stroke;g.stroke()}}
// Rendering only: actor coordinates, track IDs, smoothing and gestures come from K3.
const avatarColors=[['#8ac3a6','#355f52'],['#e1b575','#805c3b'],['#a0b4db','#4d5d80'],['#c7a0d1','#795980'],['#d59983','#81564a'],['#b9ce7c','#64793f']];
function blockLimb(g,a,b,width,color,shade){
  if(!a||!b)return;
  const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
  if(length<1)return;
  g.save();g.translate(a[0],a[1]);g.rotate(Math.atan2(dy,dx)-Math.PI/2);
  g.fillStyle=color;g.fillRect(-width/2,0,width,length);
  g.fillStyle=shade;g.fillRect(width*.15,0,width*.35,length);
  g.fillStyle='#ffffff15';g.fillRect(-width/2,0,width*.65,Math.min(width*.22,length));g.restore();
}
function avatar(g,a,w,h){
  const H=Math.max(100,a.scene_height*h),X=a.scene_x*w,Y=a.scene_y*h;
  const [color,shade]=avatarColors[(a.id-1)%avatarColors.length];
  // Retarget measured bone directions onto a fixed, connected block character.
  // Unobserved limbs remain in a muted neutral pose, never invented animation.
  const shoulderSide=a.joints[5]&&a.joints[6]?(Math.sign(a.joints[6][0]-a.joints[5][0])||-1):-1;
  const hipSide=a.joints[11]&&a.joints[12]?(Math.sign(a.joints[12][0]-a.joints[11][0])||shoulderSide):shoulderSide;
  const P={5:[shoulderSide*H*.11,-H*.69],6:[-shoulderSide*H*.11,-H*.69],11:[hipSide*H*.065,-H*.42],12:[-hipSide*H*.065,-H*.42]};
  const bones=[[5,7,.17],[7,9,.16],[6,8,.17],[8,10,.16],[11,13,.20],[13,15,.20],[12,14,.20],[14,16,.20]];
  const measured={};
  for(const [u,v,length]of bones){
    const p=a.joints[u],q=a.joints[v];let dx=0,dy=1;
    if(p&&q){const x=-(q[0]-p[0]),y=q[1]-p[1],n=Math.hypot(x,y);if(n>.008){dx=x/n;dy=y/n;measured[v]=true}}
    if(!measured[v]&&(v===7||v===8))dx=(v===7?shoulderSide:-shoulderSide)*.25;
    P[v]=[P[u][0]+dx*H*length,P[u][1]+dy*H*length];
  }
  const floor=Math.max(P[15][1],P[16][1]);
  g.save();g.translate(Math.round(X/2)*2,Math.round(Y/2)*2);g.imageSmoothingEnabled=false;
  ellipse(g,0,6,H*.22,H*.045,0,'#00000038');g.translate(0,-floor);
  for(const [u,v]of [[11,13],[13,15],[12,14],[14,16]])blockLimb(g,P[u],P[v],H*.085,measured[v]?'#526780':'#536059',measured[v]?'#33465a':'#39443d');
  g.fillStyle=color;g.fillRect(-H*.11,-H*.70,H*.22,H*.29);
  g.fillStyle=shade;g.fillRect(H*.055,-H*.70,H*.055,H*.29);
  g.fillStyle='#ffffff18';g.fillRect(-H*.11,-H*.70,H*.165,H*.035);
  g.fillStyle=shade;g.fillRect(-H*.11,-H*.46,H*.22,H*.045);
  for(const [u,v]of [[5,7],[6,8]])blockLimb(g,P[u],P[v],H*.077,measured[v]?color:'#768377',measured[v]?shade:'#4c594e');
  for(const [u,v]of [[7,9],[8,10]])blockLimb(g,P[u],P[v],H*.067,measured[v]?'#c9a27d':'#768377',measured[v]?'#8b7055':'#4c594e');
  const S=H*.19,hy=-H*.805;
  g.fillStyle='#4c4b39';g.fillRect(-S*.53,hy-S*.65,S*1.06,S*1.14);
  g.fillStyle='#caaa82';g.fillRect(-S*.5,hy-S*.36,S,S*.83);
  g.fillStyle='#a58061';g.fillRect(S*.25,hy-S*.36,S*.25,S*.83);
  g.fillStyle='#26352e';g.fillRect(-S*.26,hy-S*.03,S*.13,S*.13);g.fillRect(S*.08,hy-S*.03,S*.13,S*.13);
  g.fillStyle='#785b49';g.fillRect(-S*.12,hy+S*.27,S*.24,S*.06);
  for(const i of [9,10]){g.fillStyle=measured[i]?'#d5b58d':'#768377';g.fillRect(P[i][0]-H*.035,P[i][1]-H*.035,H*.07,H*.07)}
  for(const i of [15,16]){g.fillStyle='#293831';g.fillRect(P[i][0]-H*.05,P[i][1],H*.12,H*.04)}
  g.translate(0,floor);g.font='11px -apple-system, sans-serif';g.textAlign='center';g.fillStyle='#e0eed5';
  g.fillText(`#${a.id} · ${a.action}`,0,26);g.fillStyle='#a5b99b';g.font='9px monospace';g.fillText(`${a.visible_joints}/17`,0,40);g.restore();
}
function stripGlow(g,w,h){
  const strip=state?.strip;
  const live=strip?.status==='connected'&&performance.now()-lastGood<1500&&strip.last_sent_at>Date.parse(state.time)/1000-2;
  const target=live?(strip.sent_rgb||[0,0,0]):[0,0,0];
  const now=performance.now(),blend=1-Math.exp(-Math.max(0,now-lastGlow)/100);lastGlow=now;
  renderStrip=renderStrip.map((v,i)=>v+(target[i]-v)*blend);
  const peak=Math.max(...renderStrip);if(peak<.1)return;
  // Bounded source-over compositing: never additive/screen blending or white bloom.
  const rgb=renderStrip.map(v=>Math.round(v/peak*185));
  const alpha=Math.min(.42,strip.ambient_strength||.30)*Math.min(1,peak/38.25);
  const gradients=[[[0,0,w*.14,0],[0,0,w*.14,h]],[[w,0,w*.86,0],[w*.86,0,w*.14,h]],
                   [[0,0,0,h*.19],[0,0,w,h*.19]],[[0,h,0,h*.81],[0,h*.81,w,h*.19]]];
  g.save();g.globalCompositeOperation='source-over';
  for(const [coords,rect]of gradients){const glow=g.createLinearGradient(...coords);glow.addColorStop(0,`rgba(${rgb},${alpha})`);glow.addColorStop(.45,`rgba(${rgb},${alpha*.35})`);glow.addColorStop(1,`rgba(${rgb},0)`);g.fillStyle=glow;g.fillRect(...rect)}
  g.strokeStyle=`rgba(${rgb},${alpha*.9})`;g.lineWidth=2;g.strokeRect(1,1,w-2,h-2);g.restore();
}
function habitat(now){const[g,w,h]=context('habitat');const t=state?.telemetry||{},fresh=state?.bridge_connected && performance.now()-lastGood<3000;const night=state?.controls?.sleep;
  const bg=g.createRadialGradient(w*.5,h*.5,20,w*.5,h*.5,w*.7);bg.addColorStop(0,night?'#172721':'#273c29');bg.addColorStop(1,'#0d1e18');g.fillStyle=bg;g.fillRect(0,0,w,h);
  g.strokeStyle='#a8cc8c0a';g.lineWidth=1;for(let i=0;i<w;i+=28){g.beginPath();g.moveTo(i,0);g.lineTo(i,h);g.stroke()}for(let i=0;i<h;i+=28){g.beginPath();g.moveTo(0,i);g.lineTo(w,i);g.stroke()}
  // Botanical structures are display-only; body coordinates arrive from the board.
  for(let i=0;i<18;i++){const x=(Math.sin(i*37.2)*.5+.5)*w,y=(Math.cos(i*13.2)*.5+.5)*h;g.save();g.translate(x,y);g.rotate(i*2.3);ellipse(g,0,0,10+i%4*5,3,0,'#759b4e15','#9dc67f16');g.restore()}
  ellipse(g,w*.25,h*.7,41,25,-.35,'#b7793d25','#d6a56035');ellipse(g,w*.25,h*.7,27,17,-.35,'#ba874c35');
  for(let i=0;i<7;i++)ellipse(g,w*.25+Math.cos(i)*16,h*.7+Math.sin(i)*10,1.6,1.1,i,'#edca7c55');
  ellipse(g,w*.75,h*.72,35,17,-.2,'#4eb8a322','#8ddbc559');ellipse(g,w*.75-5,h*.72-3,19,7,-.2,null,'#9bd2bd30');
  if(state?.controls?.rain>0.5){g.strokeStyle='#b6d8ce17';for(let i=0;i<30;i++){const x=(i*73)%w,y=(i*41+now*.025)%h;g.beginPath();g.moveTo(x,y);g.lineTo(x-4,y+9);g.stroke()}}
  stripGlow(g,w,h);
  if(performance.now()-lastGood<1500 && state?.camera?.pose_fresh){
    for(const actor of [...(state.camera.actors||[])].sort((a,b)=>a.scene_y-b.scene_y))avatar(g,actor,w,h);
  }
  if(fresh){renderFly.x+=(t.x-renderFly.x)*.14;renderFly.y+=(t.y-renderFly.y)*.14;const diff=Math.atan2(Math.sin(t.angle-renderFly.angle),Math.cos(t.angle-renderFly.angle));renderFly.angle+=diff*.14}
  const x=renderFly.x*w,y=renderFly.y*h;
  ellipse(g,x,y+10,28,10,0,'#00000035');g.save();g.translate(x,y);g.rotate(renderFly.angle);g.scale(1.3,1.3);
  const phase=fresh?(t.gait_phase||0)*Math.PI*2:0,escape=fresh && t.escape;
  g.strokeStyle='#9c9a65';g.lineWidth=1.3;
  for(let side of [-1,1])for(let leg=0;leg<3;leg++){const a=phase+leg*Math.PI*.7+side;const move=fresh&&t.state==='探索'?Math.sin(a)*4:0;g.beginPath();g.moveTo(5-leg*6,side*4);g.lineTo(13-leg*11+move,side*13);g.lineTo(17-leg*13+move,side*22);g.stroke()}
  ellipse(g,-8,0,18,8,0,'#ac8b4f','#d8bf7b88');g.strokeStyle='#4a432ccc';for(let i=0;i<5;i++){g.beginPath();g.moveTo(-20+i*5,-5);g.lineTo(-20+i*5,5);g.stroke()}
  for(let side of [-1,1]){const wingAngle=side*(escape?.6+Math.sin(now*.12)*.3:.32);ellipse(g,-8,side*9,23,8,wingAngle,'#cce5c945','#cee1c988');g.strokeStyle='#deedd73b';g.beginPath();g.moveTo(4,side*4);g.lineTo(-27,side*14);g.stroke()}
  ellipse(g,4,0,9,7,0,'#6b7247','#afba7488');ellipse(g,14,0,6,7,0,'#7f7b4b');ellipse(g,16,-5,4,4,0,'#b85836','#ed9b6266');ellipse(g,16,5,4,4,0,'#b85836','#ed9b6266');
  g.strokeStyle='#ccd39388';for(let side of [-1,1]){g.beginPath();g.moveTo(19,side*2);g.lineTo(25,side*6);g.stroke()}g.restore();
  if(fresh&&t.loom_input>.05){g.strokeStyle='#eeb47d99';g.lineWidth=1;g.beginPath();g.arc(x,y,45+t.loom_input*25,0,Math.PI*2);g.stroke()}
  if(!fresh){g.fillStyle='#0b111050';g.fillRect(0,0,w,h)}
}
function brain(now){if($('controlsPanel').hidden)return;const[g,w,h]=context('brain');g.clearRect(0,0,w,h);const angle=Math.sin(now*.00012)*.22;function p(v){const x=v[1],y=v[2],z=v[3];return[w*.5+(x*Math.cos(angle)+z*Math.sin(angle))*w/21,h*.5+(y*.88-z*.23)*h/9]}
  for(const v of points){const[x,y]=p(v);g.fillStyle=v[1]<0?'#b5d48638':'#88b7a742';g.fillRect(x,y,1.3,1.3)}
  if(state?.bridge_connected&&performance.now()-lastGood<3000)for(const v of state.telemetry.spikes||[]){const[x,y]=p(v);g.fillStyle='#d9edaa';g.fillRect(x-1,y-1,2.5,2.5);g.fillStyle='#c7e6a219';g.beginPath();g.arc(x,y,5,0,7);g.fill()}
  g.strokeStyle='#74986c38';g.beginPath();g.moveTo(w*.5,h*.1);g.lineTo(w*.5,h*.9);g.stroke();g.font='9px monospace';g.fillStyle='#758c72';g.fillText('L',20,h-12);g.fillText('R',w-25,h-12);
}
function draw(now){habitat(now);brain(now);requestAnimationFrame(draw)}
fetch('/points.json').then(r=>r.json()).then(p=>points=p).catch(()=>toast('连接组点云未加载'));
poll();requestAnimationFrame(draw);
