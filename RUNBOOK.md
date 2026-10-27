# K3 运行手册

板端目录：`/home/bianbu/k3-workshop/projects/siliconfly-shenzhen`，端口 8330。

以下命令均在 **K3 的终端或 SSH 会话** 执行：

```sh
cd /home/bianbu/k3-workshop/projects/siliconfly-shenzhen
python3 workshop_manage.py start siliconfly-shenzhen
python3 workshop_manage.py logs siliconfly-shenzhen
python3 workshop_manage.py stop siliconfly-shenzhen
```

浏览器访问 `http://192.168.5.23:8330`。服务启动后在页面启用摄像头和灯带；它们不会随重启自动采集/接管。服务后台独立运行，断开 SSH 不会退出。未设置开机自启，K3 重启后运行 start。

重新构建、验收：

```sh
cd /home/bianbu/k3-workshop/projects/siliconfly-shenzhen
sh build.sh
.venv/bin/python prepare_pose.py
OMP_WAIT_POLICY=PASSIVE .venv/bin/python tests/verify_native.py
.venv/bin/python -m unittest discover -s tests -v
```

`build.sh` 检查 riscv64 架构，拒绝在 Mac 上构建运行后端。当前板上的独立 `.venv` 已准备完毕，包含从现有板端环境复制的 OpenCV、numpy、spacemit_vision、ONNX Runtime，不修改其他项目或 Gateway 环境。`board_setup.py` 为本机镜像准备脚本，其源依赖路径只适配此次现场 K3；移植到另一块板需调整该路径或安装相应 RISC-V 包。

首次部署需 Python3、g++/libgomp、SpaceMIT 视觉运行库、本地 Gateway、已经下载的 Qwen3-0.6b-q4_0。YOLOv8n-Pose 模型与 YAML 在 `models/`，来源与校验记录在 `models/pose-source.json`。模型在 K3 的项目目录内，不依赖 Mac 模型文件。

查看状态：

```sh
curl http://127.0.0.1:8330/healthz
curl http://127.0.0.1:8330/api/state
tail -40 runtime/brain.log
```

`/healthz` 的 `ok` 只说明 HTTP 服务响应；还应检查 `simulation.status`、`/api/state` 中 `bridge_connected`、`camera.status` 和 `ai.status`。界面实时显示后端离线及外设错误。

如摄像头读取失败，先检查是否被其他程序使用；不要把 `/dev/video0` 编解码节点当摄像头。本次真实采集设备为 `/dev/video1`。如灯带被其他实时源占用，应用会拒绝连接；不会自动停止其他项目。灯带输出上限 15%，不改控制器永久设置。

无网时本地神经仿真、已准备的摄像头模型和灯带仍无需云端计算；当前天气不可用，选择明确标记的人工季节场景。实际拔网离线场景尚未验证。

服务停止时终止自己的神经子进程、释放摄像头并发送熄灯帧。现场局域网演示接口没有用户登录体系，不用于公网部署。

页面默认全窗口场景。F 请求/退出原生全屏，C 打开控制面板。右下角有单色/自动变色快捷操作；自动变色在 K3 的独立灯光线程运行，摄像头关闭或神经仿真变慢不会阻止颜色更新。
