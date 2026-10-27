"""Local Gateway HTTP helpers; adapt against actual OpenAPI, not a version lock."""
from __future__ import annotations

import base64
import ipaddress
import json
import logging
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

DOMAINS = ("llm", "asr", "vision", "vlm", "embed", "tts", "vad", "rerank")
_LOCK = threading.Lock()


class GatewayError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details or {}


def unwrap(value):
    if isinstance(value, dict) and "code" in value:
        if value["code"] not in (0, 200, "0", "200"):
            raise GatewayError("GATEWAY_REJECTED", str(value.get("message") or "Gateway 推理失败"))
        return value.get("data")
    return value


def normalize_models(value):
    value = unwrap(value)
    for _ in range(2):
        if not isinstance(value, dict):
            break
        value = value.get("models", value.get("data"))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise GatewayError("INVALID_MODELS", "Gateway 模型列表格式无效")
    return [{**row, "id":row.get("id") or row.get("model_id") or row.get("model")} for row in value]


def model_state(row):
    """A legacy 'unloaded' response says nothing about files on disk."""
    if row.get("status") in ("downloading","loading"):return "preparing"
    if row.get("loaded") is True or row.get("status") in ("loaded","running","downloaded"):
        return "ready"
    if row.get("downloaded") is True:return "ready"
    if row.get("downloaded") is False or row.get("status")=="available":return "missing"
    return "unknown"


def catalog_path():
    sibling = Path(__file__).with_name("models.json")
    return sibling if sibling.exists() else Path(__file__).resolve().parent.parent / "references/models.json"


def multipart(fields, data, filename, content_type):
    boundary = "k3-workshop-" + uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    safe_name = Path(filename).name.replace('"', '').replace("\r", '').replace("\n", '')
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\nContent-Type: {content_type}\r\n\r\n'.encode())
    chunks.extend((data, f"\r\n--{boundary}--\r\n".encode()))
    return b"".join(chunks), "multipart/form-data; boundary=" + boundary


class GatewayClient:
    def __init__(self, base_url="http://127.0.0.1:18790", timeout=60):
        parsed = urllib.parse.urlsplit(base_url)
        try:
            local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            local = False
        if parsed.scheme != "http" or not local or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise GatewayError("LOCAL_GATEWAY_REQUIRED", "应用只能调用板上 loopback HTTP Gateway")
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.catalog = json.loads(catalog_path().read_text(encoding="utf-8"))
        self.active = None
        self.last_request_id = None

    def request(self, method, path, payload=None, *, raw=None, content_type=None, binary=False):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else raw
        headers = {"Accept":"application/json", "X-Request-ID":uuid4().hex}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            # Bypass notebook/board proxy variables: this request must stay on loopback.
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=self.timeout) as response:
                result = response.read()
                self.last_request_id = response.headers.get("X-Request-ID", headers["X-Request-ID"])
                if binary:
                    return result
        except urllib.error.HTTPError as error:
            detail = error.read(2048).decode("utf-8", errors="replace")
            raise GatewayError("GATEWAY_HTTP_ERROR", f"Gateway HTTP {error.code}", {"body":detail,"path":path}) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise GatewayError("GATEWAY_UNAVAILABLE", "无法连接板上的 AI Gateway", {"reason":str(error)}) from error
        try:
            return json.loads(result)
        except (ValueError, UnicodeDecodeError) as error:
            raise GatewayError("INVALID_JSON", "Gateway 未返回有效 JSON") from error

    def list_models(self, domain):
        if domain not in DOMAINS:
            raise GatewayError("UNKNOWN_DOMAIN", "未知模型域")
        return normalize_models(self.request("GET", f"/v1/{domain}/models"))

    def _installed(self, domain, model,files_confirmed=False):
        row = next((row for row in self.list_models(domain) if row["id"] == model), None)
        if not row:
            raise GatewayError("MODEL_NOT_REGISTERED", "目标模型未在设备注册")
        if row.get("source_type") == "remote" or row.get("backend") == "mock":
            raise GatewayError("NON_LOCAL_MODEL", "拒绝远程或 Mock 模型")
        state=model_state(row)
        if state=="missing":
            raise GatewayError("MODEL_NOT_DOWNLOADED", "模型尚未下载；准备阶段按实际接口和用户授权下载，应用运行时不自动下载")
        if state=="preparing":raise GatewayError("MODEL_PREPARING","模型正在下载或加载，请等待状态完成")
        if state=="unknown" and not files_confirmed:
            raise GatewayError("MODEL_DOWNLOAD_UNKNOWN","接口未报告文件就绪状态，不能将unloaded判断为未下载；请核对文件后用files_confirmed=True",{"model":row})
        return row

    @staticmethod
    def approved(domain,model):
        path=Path(os.environ.get("K3_MODEL_APPROVAL", str(Path.home()/"k3-workshop/state/model-approval.json")))
        try:
            value=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            return False
        return any(row.get("domain")==domain and row.get("model")==model and row.get("quality_review")=="approved" for row in value.get("models",[]))

    @contextmanager
    def session(self, domain, model,*,files_confirmed=False):
        if self.active:
            raise GatewayError("NESTED_MODEL", "模型步骤必须串行；先结束前一个 session")
        if not _LOCK.acquire(timeout=30):
            raise GatewayError("AI_BUSY", "已有 AI 请求执行，请稍后重试")
        lock_file = None
        attempted_load = False
        primary_error = None
        try:
            if os.name == "posix":
                import fcntl
                state = Path(os.environ.get("K3_WORKSHOP_STATE_DIR", str(Path.home()/"k3-workshop/state"))).resolve()
                state.mkdir(parents=True, exist_ok=True)
                lock_file = (state/"ai.lock").open("a")
                deadline = time.monotonic() + 30
                while True:
                    try:
                        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise GatewayError("AI_BUSY", "另一应用正在使用 K3 AI 资源")
                        time.sleep(0.05)
            selected=self._installed(domain, model,files_confirmed)
            # All workshop applications share the lock. Refuse a second resident model
            # rather than interrupting models loaded outside this application's session.
            for other_domain in DOMAINS:
                try:
                    rows = self.list_models(other_domain)
                except GatewayError:
                    if other_domain == domain:
                        raise
                    continue
                resident = [r["id"] for r in rows if r.get("loaded") is True or r.get("status") in ("loaded", "running", "loading")]
                if any(other_domain != domain or name != model for name in resident):
                    raise GatewayError("OTHER_MODEL_LOADED", "请先在控制台卸载其他模型，再执行串行流程", {"domain":other_domain,"models":resident})
            key = "model" if domain in ("llm", "vlm", "embed", "rerank") else "model_id"
            body = {key:model}
            if domain == "vision":
                body["lazy_load"] = False
            # A model loaded outside our session must not be unloaded on exit.
            if selected.get("loaded") is not True and selected.get("status") not in ("loaded","running"):
                attempted_load = True
                unwrap(self.request("POST", f"/v1/{domain}/models/load", body))
            health = unwrap(self.request("GET", f"/v1/{domain}/healthz"))
            if isinstance(health, dict) and health.get("backend") == "mock":
                raise GatewayError("MOCK_BACKEND", "拒绝 Mock 推理后端")
            self.active = (domain, model)
            yield self
        except BaseException as error:
            primary_error = error
            raise
        finally:
            self.active = None
            try:
                if attempted_load:
                    unwrap(self.request("POST", f"/v1/{domain}/models/unload", {key:model}))
            except Exception as error:
                if primary_error:
                    logging.error("模型卸载失败: %s", error)
                    if hasattr(primary_error, "add_note"):
                        primary_error.add_note("模型卸载也失败；联系助教检查 Gateway")
                else:
                    raise GatewayError("UNLOAD_FAILED", "推理后模型卸载失败，请检查 Gateway", {"reason":str(error)}) from error
            finally:
                if lock_file:
                    lock_file.close()
                _LOCK.release()

    def _model(self, domain):
        if not self.active or self.active[0] != domain:
            raise GatewayError("SESSION_REQUIRED", f"请在 {domain} session 中调用推理")
        return self.active[1]

    def chat(self, text, *, system="请用中文简洁回答。/no_think", max_tokens=256):
        if not text.strip() or len(text) > 1500 or not 1 <= max_tokens <= 256:
            raise GatewayError("INPUT_BUDGET", "文本需为1–1500字符，回答上限1–256 tokens")
        value = unwrap(self.request("POST", "/v1/llm/chat/completions", {
            "model":self._model("llm"), "messages":[{"role":"system","content":system},{"role":"user","content":text}],
            "max_tokens":max_tokens, "temperature":0.2, "stream":False}))
        return self._answer(value)

    @staticmethod
    def _answer(value):
        try:
            text = value["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise GatewayError("INVALID_ANSWER", "模型没有返回可显示的回答") from error
        if not isinstance(text, str) or not text.strip():
            raise GatewayError("EMPTY_ANSWER", "模型回答为空；检查输出预算与非思考模式")
        return text.strip()

    def transcribe(self, audio, filename="sample.wav"):
        raw, content_type = multipart({"model":self._model("asr"),"language":"zh"}, audio, filename, "audio/wav")
        value = unwrap(self.request("POST", "/v1/asr/recognize", raw=raw, content_type=content_type))
        text = value.get("text") if isinstance(value, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise GatewayError("EMPTY_TRANSCRIPT", "音频未识别到文字")
        return text.strip()

    def detect(self, image):
        value = unwrap(self.request("POST", "/v1/vision/inference", {
            "model_id":self._model("vision"), "tasks":["detect"],
            "image_base64":base64.b64encode(image).decode(), "render":True,"render_mode":"overlay"}))
        if not isinstance(value, dict) or "results" not in value:
            raise GatewayError("INVALID_DETECTION", "对象检测结果格式无效")
        return value

    def describe(self, image, mime="image/jpeg", question="用两句话描述这张图片。"):
        value = unwrap(self.request("POST", "/v1/vlm/chat/completions", {
            "model":self._model("vlm"), "messages":[{"role":"user","content":[
                {"type":"text","text":question}, {"type":"image_url","image_url":{"url":f"data:{mime};base64,"+base64.b64encode(image).decode()}}]}],
            "max_tokens":128,"stream":False}))
        return self._answer(value)

    def embed(self, texts):
        value = self.request("POST", "/v1/embed/embeddings", {"model":self._model("embed"),"input":texts})
        try:
            rows = sorted(value["data"], key=lambda item:item["index"])
            vectors = [row["embedding"] for row in rows]
            if len(vectors) != len(texts) or not vectors or not vectors[0]:
                raise ValueError()
            if [row["index"] for row in rows] != list(range(len(texts))) or any(len(v) != len(vectors[0]) or any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) for x in v) for v in vectors):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError) as error:
            raise GatewayError("INVALID_EMBEDDING", "向量数量、索引、维度或数值无效") from error

    def speak(self, text):
        data = self.request("POST", "/v1/tts/synthesize", {"model":self._model("tts"),"text":text,"response_format":"wav"}, binary=True)
        if not data.startswith(b"RIFF"):
            raise GatewayError("INVALID_AUDIO", "TTS 未返回 WAV 音频")
        return data
