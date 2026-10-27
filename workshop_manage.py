"""Board-side app setup/deploy/start/stop; confined to ~/k3-workshop."""
import argparse
import importlib.metadata
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

KIT=Path(__file__).resolve().parents[1]
ROOT=Path.home()/"k3-workshop"


def project_path(name):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}",name):
        raise ValueError("项目名需为小写字母开头，最多40位字母数字或短横线")
    return ROOT/"projects"/name


def write_json(path,value):
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(path)


def settings(name):
    value=json.loads((project_path(name)/"project.json").read_text(encoding="utf-8"))
    port=value.get("port",8080)
    if isinstance(port,bool) or not isinstance(port,int) or not 1024<=port<=65535:
        raise ValueError("应用端口必须为1024–65535整数")
    if not isinstance(value.get("command"),list) or not value["command"] or any(not isinstance(x,str) or not x for x in value["command"]):
        raise ValueError("project.json需要非空command数组，不使用shell命令串")
    health=value.get("health_path","/healthz")
    if not isinstance(health,str) or not health.startswith("/") or health.startswith("//"):
        raise ValueError("health_path需要站内路径，例如/healthz")
    return {**value,"port":port,"health_path":health}


def command_for(name,value):
    choices=(project_path(name)/".venv/bin/python",ROOT/"venv/bin/python")
    python=next((str(p) for p in choices if p.is_file()),sys.executable)
    return [item.replace("{python}",python).replace("{port}",str(value["port"])) for item in value["command"]]


def process_info(pid):
    base=Path(f"/proc/{pid}")
    if not (base/"stat").exists():return None
    stat=(base/"stat").read_text().rsplit(")",1)[1].split()
    if stat[0]=="Z":return None
    return {"start_tick":stat[19],"cwd":(base/"cwd").resolve(),
            "command":[x.decode(errors="replace") for x in (base/"cmdline").read_bytes().split(b"\0") if x]}


def safe_extract(archive,destination):
    destination=Path(destination).resolve()
    with tarfile.open(archive,"r:gz") as bundle:
        members=bundle.getmembers()
        if len(members)>10000 or sum(member.size for member in members)>100*1024**2:
            raise ValueError("项目源码压缩包最多10000项、解压100MiB")
        for member in members:
            target=(destination/member.name).resolve()
            if not target.is_relative_to(destination) or not (member.isfile() or member.isdir()):
                raise ValueError("压缩包包含越界路径、链接或特殊文件")
        if sys.version_info>=(3,12):
            bundle.extractall(destination,members=members,filter="data")
        else:
            bundle.extractall(destination,members=members)


def running(name):
    pidfile=ROOT/"state"/(name+".pid.json")
    if not pidfile.exists():
        return None
    row=json.loads(pidfile.read_text())
    actual=process_info(row["pid"])
    if actual is None:return None
    matching=actual["command"]==row["command"] if "command" in row else "uvicorn app:app" in " ".join(actual["command"])
    if not matching or actual["cwd"]!=project_path(name).resolve() or actual["start_tick"]!=row["start_tick"]:
        raise ValueError("PID记录与进程不匹配，未发送停止信号；请助教检查")
    return row


def stop(name):
    row=running(name)
    if row:
        os.kill(row["pid"],signal.SIGTERM)
        deadline=time.monotonic()+10
        while running(name) and time.monotonic()<deadline:
            time.sleep(0.1)
        if running(name):
            raise RuntimeError("进程未在10秒内退出；请助教查看日志，不自动强制终止")
    pidfile=ROOT/"state"/(name+".pid.json")
    pidfile.unlink(missing_ok=True)
    print("应用已停止；源码、日志、模型均保留")


def start(name,port=None):
    target=project_path(name)
    if running(name):
        raise ValueError("应用已经运行")
    value=settings(name)
    if port is not None:
        if isinstance(port,bool) or not isinstance(port,int) or not 1024<=port<=65535:
            raise ValueError("应用端口必须为1024–65535整数")
        value["port"]=port
    port=value["port"]
    command=command_for(name,value)
    for folder in ("state","logs"):
        (ROOT/folder).mkdir(parents=True,exist_ok=True)
    with socket.socket() as check:
        # Match HTTPServer's reuse policy: TIME_WAIT after our shutdown is not
        # another running service. This still rejects an active listening socket.
        check.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:
            check.bind(("0.0.0.0",port))
        except OSError as error:
            raise ValueError(f"{port}端口已占用；请换端口，不停止已有服务") from error
    write_json(target/"project.json",value)
    with (ROOT/"logs"/(name+".log")).open("ab") as log:
        environment={**os.environ,"K3_WORKSHOP_STATE_DIR":str(ROOT/"state"),"K3_APP_PORT":str(port)}
        environment.pop("K3_REQUIRE_MODEL_APPROVAL",None)
        process=subprocess.Popen(command,cwd=target,stdout=log,stderr=log,start_new_session=True,env=environment)
    info=process_info(process.pid)
    if info is None:raise RuntimeError(f"应用启动后立即退出；检查依赖、启动命令和 {ROOT/'logs'/(name+'.log')}")
    row={"pid":process.pid,"start_tick":info["start_tick"],"command":command,"port":port}
    pidfile=ROOT/"state"/(name+".pid.json")
    write_json(pidfile,row)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise RuntimeError(f"应用启动失败，查看 {ROOT/'logs'/(name+'.log')}")
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}{value['health_path']}",timeout=1) as response:
                if response.status==200:
                    print(f"应用已启动，访问 http://<板子IP>:{port}；模型推理尚需单独验证")
                    return
        except OSError:
            time.sleep(0.2)
    stop(name)
    raise RuntimeError("/healthz未就绪，查看应用日志")


def setup(wheelhouse,use_installed,name=None,allow_network=False):
    target=project_path(name) if name else ROOT
    env=target/".venv" if name else ROOT/"venv"
    requirements=target/"requirements.txt" if name else KIT/"skills/k3-app-builder/assets/starter/requirements.txt"
    if env.exists():
        raise ValueError("venv已存在，不覆盖；先检查已有环境")
    if not wheelhouse and not use_installed and not allow_network:
        raise ValueError("请指定--wheelhouse，或在确认联网安装权限后使用--allow-network；不修改系统或Gateway环境")
    target.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,"-m","venv"]
    if use_installed:
        command.append("--system-site-packages")
    command.append(str(env))
    subprocess.run(command,check=True)
    python=env/"bin/python"
    if requirements.is_file() and requirements.read_text(encoding="utf-8").strip() and (wheelhouse or allow_network):
        source=["--no-index","--find-links",str(wheelhouse)] if wheelhouse else []
        subprocess.run([str(python),"-m","pip","install",*source,"-r",str(requirements)],check=True)
    freeze=subprocess.run([str(python),"-m","pip","freeze"],check=True,capture_output=True,text=True).stdout
    (ROOT/"state").mkdir(exist_ok=True)
    (ROOT/"state"/((name or "shared")+"-environment.txt")).write_text(freeze,encoding="utf-8")
    print("独立workshop环境已准备；实际版本已记录，不修改Gateway环境")


def deploy(name,archive):
    target=project_path(name)
    if running(name):
        raise ValueError("请先stop再deploy，不覆盖正在运行的应用")
    target.parent.mkdir(parents=True,exist_ok=True)
    staging=target.parent/(name+".staging-"+uuid4().hex)
    staging.mkdir()
    safe_extract(archive,staging)
    if not (staging/"project.json").is_file():
        raise ValueError(f"源码包根目录缺少project.json；解压结果保留在 {staging}")
    if target.exists():
        backup=target.parent/(name+".backup-"+uuid4().hex)
        target.rename(backup)
        print(f"上一版源码保存在 {backup}")
    staging.rename(target)
    print(f"已部署 {target}；不会自动安装新依赖")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    setup_parser=sub.add_parser("setup")
    setup_parser.add_argument("project",nargs="?")
    setup_parser.add_argument("--wheelhouse",type=Path)
    setup_parser.add_argument("--use-installed",action="store_true")
    setup_parser.add_argument("--allow-network",action="store_true")
    for action in ("init","start","stop","logs","deploy"):
        command=sub.add_parser(action)
        command.add_argument("project")
        if action=="init":command.add_argument("--route",choices=("starter","zero"),default="zero")
        if action=="start":command.add_argument("--port",type=int)
        if action=="deploy":command.add_argument("archive",type=Path)
    args=parser.parse_args()
    if os.name!="posix":
        parser.error("manage.py只在K3/Linux执行；笔记本使用包装脚本或init_project.py")
    if args.action=="setup":setup(args.wheelhouse,args.use_installed,args.project,args.allow_network)
    elif args.action=="init":
        from init_project import create
        print(create(project_path(args.project),args.route))
    elif args.action=="start":start(args.project,args.port)
    elif args.action=="stop":stop(args.project)
    elif args.action=="deploy":deploy(args.project,args.archive)
    else:
        log=ROOT/"logs"/(args.project+".log")
        project_path(args.project)
        print("\n".join(log.read_text(errors="replace").splitlines()[-80:]) if log.exists() else "暂无日志")


if __name__=="__main__":
    try:
        main()
    except (ValueError,RuntimeError,OSError,subprocess.CalledProcessError) as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(2)
