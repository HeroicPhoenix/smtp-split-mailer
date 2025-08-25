import os
import re
import tarfile
import time
import socket
import platform
import subprocess
import logging
from pathlib import Path
from threading import Thread, Lock
from typing import List, Optional, Dict

import yaml
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from email.message import EmailMessage
from email.header import Header
from email.utils import getaddresses
import smtplib

# ---------------- Paths ----------------
APP_DIR = Path(__file__).resolve().parent.parent  # 项目根
APP_DIR_SELF = Path(__file__).resolve().parent    # app/ 目录
STATIC_DIR = APP_DIR_SELF / "static"              # 前端目录 app/static

DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else APP_DIR / "data"))

UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
SEVENZ_DIR  = DATA_DIR / "7z"
BIN_DIR     = DATA_DIR / "bin"
CONFIG_FILE = APP_DIR / "config" / "config.yaml"
LOG_FILE    = DATA_DIR / "logs" / "app.log"

for p in [UPLOADS_DIR, OUTPUTS_DIR, SEVENZ_DIR, BIN_DIR, LOG_FILE.parent]:
    p.mkdir(parents=True, exist_ok=True)

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("split-mailer")

# ---------------- Config helpers ----------------
def load_yaml_config(path: Path) -> Dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            try:
                return yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"读取 config.yaml 失败: {e}")
                return {}
    return {}

CFG = load_yaml_config(CONFIG_FILE)

def cfg(key: str, default=None):
    val = os.getenv(key)
    if val is None:
        if key in CFG:
            return CFG.get(key, default)
        return CFG.get(key.lower(), default)
    return val

def cfg_int(key: str, default: int):
    v = cfg(key, default)
    try:
        return int(v)
    except Exception:
        return default

def cfg_bool(key: str, default: bool):
    v = str(cfg(key, default)).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

# ---------------- 7z setup ----------------
def ensure_7z_ready() -> Path:
    sevenz_path = SEVENZ_DIR / "7zz"
    if sevenz_path.exists():
        logger.info(f"7z 已就绪: {sevenz_path}")
        return sevenz_path

    forced = os.getenv("SEVENZ_TARBALL")
    if forced:
        tar_path = BIN_DIR / forced
        if not tar_path.exists():
            raise RuntimeError(f"未找到 {tar_path}（请确认放在 ./bin/ 下）")
    else:
        sys = platform.system().lower()
        arch = platform.machine().lower()
        if sys == "darwin":
            candidates = ["7z2501-mac.tar.xz", "7z-mac.tar.xz", "7z-macos.tar.xz"]
        elif sys == "linux":
            is_arm = any(k in arch for k in ["aarch64", "arm64"])
            candidates = ["7z2501-linux-arm64.tar.xz"] if is_arm else ["7z2501-linux-x64.tar.xz"]
        else:
            raise RuntimeError(f"不支持的系统：{platform.system()}（可设置 SEVENZ_TARBALL 环境变量手动选择包）")

        tar_path = None
        for name in candidates:
            p = BIN_DIR / name
            if p.exists():
                tar_path = p
                break
        if tar_path is None:
            raise RuntimeError(f"未在 ./bin/ 中找到可用 7z 压缩包：{', '.join(candidates)}")

    with tarfile.open(tar_path, "r:xz") as tf:
        members = [m for m in tf.getmembers() if m.name.endswith("/7zz") or m.name == "7zz" or m.name.endswith("/7z.so")]
        if not members:
            tf.extractall(SEVENZ_DIR)
        else:
            for m in members:
                m.name = Path(m.name).name
                tf.extract(m, SEVENZ_DIR)

    try:
        os.chmod(sevenz_path, 0o755)
    except Exception as e:
        logger.info(f"设置 7zz 可执行权限失败（可忽略或手动 chmod +x）: {e}")

    if not sevenz_path.exists():
        found = list(SEVENZ_DIR.rglob("7zz"))
        if found:
            try:
                os.chmod(found[0], 0o755)
            except Exception:
                pass
            return found[0]
        raise RuntimeError(f"未在 {SEVENZ_DIR} 中找到 7zz，请检查压缩包结构")

    return sevenz_path

SEVENZ_PATH: Optional[Path] = None

# ---------------- Email helpers ----------------
_FULLWIDTH_MAP = str.maketrans({
    "，": ",",
    "；": ";",
    "。": ".",
    "＠": "@",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "：": ":",
    "、": ",",
    "\u3000": " ",
})

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)

def _normalize_emails_text(s: str) -> str:
    if not s:
        return ""
    s = s.translate(_FULLWIDTH_MAP)
    s = re.sub(r"\s*([@.])\s*", r"\1", s)
    s = re.sub(r"[;\s，；、]+", ",", s)
    s = s.strip(" ,;")
    return s

def parse_recipients(s: str) -> List[str]:
    s = _normalize_emails_text(s)
    if not s:
        return []
    pairs = getaddresses([s])
    emails, bad = [], []
    for _name, addr in pairs:
        addr = addr.strip()
        if not addr:
            continue
        if _EMAIL_RE.match(addr):
            emails.append(addr)
        else:
            bad.append(addr)
    if bad:
        raise RuntimeError(f"无效邮箱：{', '.join(bad)}")
    seen, uniq = set(), []
    for e in emails:
        el = e.lower()
        if el not in seen:
            seen.add(el)
            uniq.append(e)
    return uniq

def connect_smtp(host: str, port: int, username: str, password: str, use_ssl: bool, use_tls: bool):
    timeout_sec = cfg_int("SMTP_TIMEOUT", 120)
    debug = cfg_bool("SMTP_DEBUG", False)

    logger.info(f"SMTP 连接准备：host={host}, port={port}, ssl={use_ssl}, tls={use_tls}, timeout={timeout_sec}s")

    try:
        ip_list = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ip_str = ", ".join(sorted({ai[4][0] for ai in ip_list}))
        logger.info(f"SMTP DNS 解析成功：{host} -> {ip_str}")
    except Exception as e:
        raise RuntimeError(f"SMTP DNS 解析失败：{host}:{port} -> {e}")

    try:
        t0 = time.time()
        server = smtplib.SMTP_SSL(host, port, timeout=timeout_sec) if use_ssl else smtplib.SMTP(host, port, timeout=timeout_sec)
        if debug:
            server.set_debuglevel(1)
        logger.info(f"SMTP 已建立 TCP 连接（{'SSL' if use_ssl else 'PLAIN'}），耗时 {time.time()-t0:.2f}s")
    except Exception as e:
        raise RuntimeError(f"SMTP 连接失败（SSL={use_ssl}）：{e}")

    try:
        t0 = time.time()
        server.ehlo()
        logger.info(f"SMTP EHLO 完成，耗时 {time.time()-t0:.2f}s")
    except Exception as e:
        server.close()
        raise RuntimeError(f"SMTP EHLO 失败：{e}")

    if use_tls and not use_ssl:
        try:
            t0 = time.time()
            server.starttls(timeout=timeout_sec)
            server.ehlo()
            logger.info(f"SMTP STARTTLS 握手完成，耗时 {time.time()-t0:.2f}s")
        except Exception as e:
            server.close()
            raise RuntimeError(f"SMTP STARTTLS 失败：{e}")

    if username:
        try:
            t0 = time.time()
            server.login(username, password)
            logger.info(f"SMTP 登录成功（user={username}），耗时 {time.time()-t0:.2f}s")
        except Exception as e:
            server.close()
            raise RuntimeError(f"SMTP 登录失败：{e}")

    try:
        server.sock.settimeout(timeout_sec)
    except Exception:
        pass

    return server

def pick_sender(username: str) -> str:
    env_from = (cfg("SMTP_FROM", "") or "").strip()
    if env_from:
        return env_from
    if username:
        return username
    return f"no-reply@{socket.gethostname()}"

# ---------------- Task manager ----------------
class JobStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    ERROR = "ERROR"

class Job:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = JobStatus.PENDING
        self.logs: List[str] = []
        self.lock = Lock()

    def log(self, msg: str, level: str = "info"):
        with self.lock:
            stamp = time.strftime("%H:%M:%S")
            self.logs.append(f"[{stamp}] {msg}")
            if len(self.logs) > 2000:
                self.logs = self.logs[-1000:]
        if level == "error":
            logger.error(msg)
        else:
            logger.info(msg)

JOBS: Dict[str, Job] = {}
JOBS_LOCK = Lock()

def create_job() -> Job:
    job_id = str(int(time.time() * 1000))
    j = Job(job_id)
    with JOBS_LOCK:
        JOBS[job_id] = j
    return j

def get_job(job_id: str) -> Optional[Job]:
    with JOBS_LOCK:
        return JOBS.get(job_id)

# ---------------- Schemas ----------------
class StartPayload(BaseModel):
    session_id: str
    output_basename: str = Field(default_factory=lambda: cfg("DEFAULT_OUTPUT_BASENAME", "mydata"))
    subject_prefix: str = Field(default_factory=lambda: cfg("DEFAULT_SUBJECT_PREFIX", "项目资料-分卷传输"))
    volume_size_mb: int = Field(default_factory=lambda: cfg_int("DEFAULT_VOLUME_SIZE_MB", 20))
    send_interval_sec: int = Field(default_factory=lambda: cfg_int("DEFAULT_SEND_INTERVAL_SEC", 5))
    recipients: str = Field(default_factory=lambda: cfg("DEFAULT_RECIPIENTS", ""))
    cc: str = Field(default_factory=lambda: cfg("DEFAULT_CC", ""))

    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_ssl: Optional[bool] = None
    smtp_use_tls: Optional[bool] = None

class SMTPTestPayload(BaseModel):
    host: str
    port: int
    username: str = ""
    password: str = ""
    use_ssl: bool = False
    use_tls: bool = True

# ---------------- App ----------------
app = FastAPI(title="Folder Split-Mailer", version="1.2.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def root():
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/", response_class=HTMLResponse)
    def root():
        return HTMLResponse(
            "<h3>前端目录未找到</h3>"
            f"<p>期望路径：{STATIC_DIR}</p>"
            "<p>请确认 app/static/index.html 是否存在。</p>"
        )

@app.get("/api/defaults")
def api_defaults():
    return {
        "output_basename": cfg("DEFAULT_OUTPUT_BASENAME", "mydata"),
        "subject_prefix": cfg("DEFAULT_SUBJECT_PREFIX", "项目资料-分卷传输"),
        "volume_size_mb": cfg_int("DEFAULT_VOLUME_SIZE_MB", 20),
        "send_interval_sec": cfg_int("DEFAULT_SEND_INTERVAL_SEC", 5),
        "recipients": cfg("DEFAULT_RECIPIENTS", ""),
        "cc": cfg("DEFAULT_CC", ""),
        "smtp_host": cfg("SMTP_HOST", ""),
        "smtp_port": cfg_int("SMTP_PORT", 465),
        "smtp_username": cfg("SMTP_USERNAME", ""),
        "smtp_password": cfg("SMTP_PASSWORD", ""),
        "smtp_use_ssl": cfg_bool("SMTP_USE_SSL", True),
        "smtp_use_tls": cfg_bool("SMTP_USE_TLS", False),
    }

@app.post("/api/upload")
async def api_upload(
    session_id: str = Form(...),
    files: List[UploadFile] = File(...),
    paths: List[str] = Form(...),
):
    base = UPLOADS_DIR / session_id
    base.mkdir(parents=True, exist_ok=True)

    if len(paths) != len(files):
        raise HTTPException(400, "files 和 paths 长度不一致")

    saved = []
    for i, uf in enumerate(files):
        rel = Path(paths[i])
        target_path = base / rel
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as out:
            out.write(await uf.read())
        saved.append(str(rel))

    logger.info(f"上传完成: session={session_id}, 文件数={len(saved)}")
    return {"ok": True, "saved": saved, "count": len(saved)}

@app.get("/api/list")
def api_list(session_id: str):
    out_dir = OUTPUTS_DIR / session_id
    if not out_dir.exists():
        return {"parts": [], "total": 0}
    parts, total = [], 0
    for p in sorted(out_dir.glob("*.7z.*")):
        size = p.stat().st_size if p.exists() else 0
        parts.append({"name": p.name, "size": size})
        total += size
    return {"parts": parts, "total": total}

@app.get("/api/logs")
def api_logs(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"status": job.status, "logs": job.logs[-1000:]}

@app.post("/api/test-smtp")
def api_test_smtp(payload: SMTPTestPayload):
    try:
        srv = connect_smtp(payload.host, payload.port, payload.username, payload.password, payload.use_ssl, payload.use_tls)
        srv.noop()
        srv.quit()
        return {"ok": True, "message": "SMTP 连接正常"}
    except Exception as e:
        logger.error(f"SMTP 测试失败: {e}")
        return JSONResponse(status_code=400, content={"ok": False, "message": str(e)})

def _run_job(job: Job, payload: StartPayload):
    job.status = JobStatus.RUNNING
    try:
        # ---------- 先解析 SMTP 并做预检（不通过则立即失败，避免白压缩） ----------
        host = (payload.smtp_host or cfg("SMTP_HOST", "")).strip()
        port = payload.smtp_port if payload.smtp_port is not None else cfg_int("SMTP_PORT", 465)
        username = (payload.smtp_username or cfg("SMTP_USERNAME", "")).strip()
        password = (payload.smtp_password or cfg("SMTP_PASSWORD", "")).strip()
        use_ssl = payload.smtp_use_ssl if payload.smtp_use_ssl is not None else cfg_bool("SMTP_USE_SSL", True)
        use_tls = payload.smtp_use_tls if payload.smtp_use_tls is not None else cfg_bool("SMTP_USE_TLS", False)

        if not host:
            raise RuntimeError("未配置 SMTP_HOST（请在前端或环境变量中提供）")

        job.log("进行 SMTP 预检（联通性与登录）...")
        try:
            test_srv = connect_smtp(host, port, username, password, use_ssl, use_tls)
            test_srv.noop()
            test_srv.quit()
            job.log("SMTP 预检通过")
        except Exception as e:
            raise RuntimeError(f"SMTP 预检失败：{e}")

        # ---------- 目录检查 ----------
        session_dir = UPLOADS_DIR / payload.session_id
        if not session_dir.exists():
            raise RuntimeError("未找到上传目录，请先上传文件夹")

        out_dir = OUTPUTS_DIR / payload.session_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # ---------- 压缩 ----------
        global SEVENZ_PATH
        job.log("准备压缩工具...")
        sevenz = SEVENZ_PATH or ensure_7z_ready()
        logger.info(f"7z 可执行: {sevenz}")

        base = (payload.output_basename or "mydata").strip() or "mydata"
        archive_path = out_dir / f"{base}.7z"

        old_parts = list(out_dir.glob(f"{base}.7z.*"))
        if archive_path.exists() or old_parts:
            job.log("清理上次生成的分卷")
            for p in old_parts:
                try:
                    p.unlink()
                except Exception as e:
                    logger.error(f"删除旧分卷失败: {p} -> {e}")
            try:
                if archive_path.exists():
                    archive_path.unlink()
            except Exception as e:
                logger.error(f"删除旧主文件失败: {archive_path} -> {e}")

        vsize = max(1, int(payload.volume_size_mb))
        cmd = [str(sevenz), "a", "-y", f"-v{vsize}m", "-mx=3", str(archive_path), "."]
        job.log("开始压缩源文件夹")
        logger.info(f"压缩命令: {' '.join(cmd)}")
        logger.info(f"工作目录: {session_dir}")

        proc = subprocess.Popen(cmd, cwd=str(session_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            logger.info(line.rstrip())
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"压缩失败，退出码 {ret}")

        parts = sorted(out_dir.glob(f"{base}.7z.*"))
        if not parts:
            raise RuntimeError("未生成任何分卷文件")
        job.log(f"压缩完成，共 {len(parts)} 份")

        # ---------- 发送 ----------
        job.log("开始发送邮件")
        logger.info(f"SMTP(最终生效): host={host} port={port} ssl={use_ssl} tls={use_tls}")
        server = connect_smtp(host, port, username, password, use_ssl, use_tls)

        to_list = parse_recipients(payload.recipients)
        cc_list = parse_recipients(payload.cc)
        if not to_list:
            raise RuntimeError("收件人为空")

        subject_prefix = (payload.subject_prefix or "项目资料-分卷传输").strip() or "项目资料-分卷传输"
        total = len(parts)
        from_addr = pick_sender(username)
        interval = max(0, int(payload.send_interval_sec))

        logger.info(f"发件人: {from_addr}")
        logger.info(f"收件人: {to_list}, 抄送: {cc_list}")

        for idx, part in enumerate(parts, start=1):
            msg = EmailMessage()
            subj = f"{subject_prefix} - {base} (Part {idx}/{total})"
            msg["Subject"] = str(Header(subj, "utf-8"))
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_list)
            if cc_list:
                msg["Cc"] = ", ".join(cc_list)
            msg.set_content(f"请查收分卷压缩包（{idx}/{total}）：{part.name}")

            with open(part, "rb") as f:
                data = f.read()
            msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=part.name)

            all_rcpts = to_list + cc_list
            server.send_message(msg, from_addr=from_addr, to_addrs=all_rcpts)
            job.log(f"已发送第 {idx}/{total} 封")
            logger.info(f"发送成功: {part.name} -> to={all_rcpts}")
            if idx < total and interval > 0:
                job.log(f"等待 {interval}s 继续")
                time.sleep(interval)

        server.quit()
        job.log("全部发送完成")
        job.status = JobStatus.DONE

    except Exception as e:
        job.log(f"出错：{e}", level="error")
        job.status = JobStatus.ERROR

@app.post("/api/start")
def api_start(payload: StartPayload):
    job = create_job()
    t = Thread(target=_run_job, args=(job, payload), daemon=True)
    t.start()
    return {"job_id": job.job_id, "status": job.status}

@app.get("/api/health")
def api_health():
    return {"ok": True}

@app.on_event("startup")
def _prepare_sevenz_on_startup():
    global SEVENZ_PATH
    try:
        logger.info("初始化 7z 工具...")
        SEVENZ_PATH = ensure_7z_ready()
        logger.info(f"7z 初始化完成：{SEVENZ_PATH}")
    except Exception as e:
        logger.error(f"初始化 7z 失败：{e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=12083, reload=True)
