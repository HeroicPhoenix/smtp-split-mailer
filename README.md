
# smtp-split-mailer · 分卷邮件发送器

将**整文件夹**打包为 **7z 分卷**，并通过 **SMTP** 按序逐封发送。前端原生 HTML/JS，后端 **FastAPI**。内置多平台 `7zz` 压缩工具（首次运行自动解包）。

> 适用：把大体量工程/资料通过邮件可靠传输；或仅做分卷压缩。

---

## 目录结构

```
smtp-split-mailer/
├─ app/
│  ├─ bin/                         # 内置 7z 包（首次运行自动解包出 7zz）
│  │  ├─ 7z2501-linux-arm64.tar.xz
│  │  ├─ 7z2501-linux-x64.tar.xz
│  │  └─ 7z2501-mac.tar.xz
│  ├─ config/config.yaml           # 默认配置（可被环境变量覆盖）
│  ├─ static/index.html            # 前端（带上传进度条/日志）
│  └─ main.py                      # FastAPI 后端（app 实例）
├─ data/                           # 运行后生成（可用 DATA_DIR 自定义到 /data）
│  ├─ 7z/7zz                       # 自动解包出的 7zz 可执行文件
│  ├─ logs/app.log                 # 运行日志
│  ├─ outputs/                     # 生成的分卷（按 session_id）
│  └─ uploads/                     # 上传的源文件（按 session_id）
├─ Dockerfile
├─ requirements.txt
└─ README.md
```

---

## 功能亮点

- 一键**上传文件夹**（`webkitdirectory`）并显示**实时上传进度条**
- **7z 分卷压缩**：自动识别 macOS / Linux x64 / Linux ARM64 的 `7zz`
- **SMTP 预检**：DNS/连接/握手/登录全链路检查，失败则不进入压缩/发送
- **逐封发送**：自定义主题前缀、收件人/抄送、发送间隔
- **实时日志**：前端每秒轮询 `/api/logs` 展示任务状态
- 配置优先级：**环境变量 > `config.yaml` > 内置默认**

---

## 配置

### `app/config/config.yaml`（示例）
```yaml
# 默认配置（会被同名环境变量覆盖）
default_output_basename: "mydata"
default_subject_prefix: "项目资料-分卷传输"
default_volume_size_mb: 20
default_send_interval_sec: 5

default_recipients: "a@xxx.com,b@xxx.com"
default_cc: ""

# SMTP
smtp_host: "xxx.xxx.com"
smtp_port: 465
smtp_username: "yourname@xxx.com"
smtp_password: "授权码或密码"
smtp_use_ssl: true
smtp_use_tls: false
```

### 环境变量（覆盖同名配置）

| 环境变量 | 说明 |
|---|---|
| `DATA_DIR` | 数据根目录（默认优先 `/data`，否则 `app/data`） |
| `DEFAULT_OUTPUT_BASENAME` | 输出 7z 基名 |
| `DEFAULT_SUBJECT_PREFIX` | 邮件主题前缀 |
| `DEFAULT_VOLUME_SIZE_MB` | 分卷大小（MB） |
| `DEFAULT_SEND_INTERVAL_SEC` | 发送间隔（秒） |
| `DEFAULT_RECIPIENTS` / `DEFAULT_CC` | 默认收件人/抄送 |
| `SMTP_HOST` / `SMTP_PORT` | SMTP 服务器与端口（SSL 常 465，TLS 常 587） |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP 登录凭据 |
| `SMTP_USE_SSL` / `SMTP_USE_TLS` | SSL 与 TLS（二选一，前端互斥切换） |
| `SMTP_FROM` | 自定义发件人地址（可选，否则使用用户名） |
| `SMTP_TIMEOUT` | 超时秒数（默认 120） |
| `SMTP_DEBUG` | SMTP 调试输出（true/false） |
| `SEVENZ_TARBALL` | 强制选择内置 7z 包名，如 `7z2501-linux-x64.tar.xz` |

---

## 本地运行

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 启动服务（两种等价写法）
# a. 使用 uvicorn 指定模块路径
python -m uvicorn app.main:app --host 0.0.0.0 --port 12083 --reload
# b. 直接运行 main.py（同端口 12083）
python app/main.py
```

打开浏览器访问：<http://localhost:12083/>

---

## Docker 运行

项目已提供 Dockerfile（基础镜像：`python:3.10-slim` 衍生，预装 `xz-utils tar ca-certificates`）。

### 构建镜像
```bash
docker build -t smtp-split-mailer:latest .
```

### 运行容器
```bash
docker run -d --name smtp-split-mailer   -p 12083:12083   -e SMTP_HOST=smtp.qq.com   -e SMTP_PORT=465   -e SMTP_USERNAME=you@x.com   -e SMTP_PASSWORD=xxxx   -e SMTP_USE_SSL=true   -v $(pwd)/data:/data   smtp-split-mailer:latest   uvicorn main:app --host 0.0.0.0 --port 12083 --log-level warning --no-access-log
```

> **群晖/NAS**：将宿主目录挂载为 `/data`，可持久化上传、分卷与日志。

---

## 前端使用流程

1. 点击 **“读取默认配置”**（从 `/api/defaults` 拉取默认值）  
2. 点击 **“选择并上传文件夹”**，自动开始上传并显示**进度条**  
3. 填写 **收件人/抄送**、**主题前缀**、**分卷大小**、**发送间隔**  
4. 点击 **“测试 SMTP”**（可选；开始任务时会自动预检）  
5. 点击 **“开始分卷并发送”**，右侧日志实时刷新，状态 **DONE** 即完成  
6. 点击 **“列出分卷”** 可查看当前 session 生成的分卷文件列表

> 分卷文件位于 `data/outputs/<session_id>/`：`<basename>.7z.001`、`<basename>.7z.002`…

---

## API

- `GET /` — 前端页面（`app/static/index.html`）  
- `GET /api/health` — 健康检查  
- `GET /api/defaults` — 返回默认参数与 SMTP 默认值  
- `POST /api/upload` — 上传目录（`multipart/form-data`：`session_id`、多组 `files` 与对应 `paths`）  
- `GET /api/list?session_id=xxx` — 列出已生成的分卷  
- `POST /api/test-smtp` — 预检 SMTP（JSON：`host/port/username/password/use_ssl/use_tls`）  
- `POST /api/start` — 启动压缩+发送（请求体示例）：
```json
{
  "session_id": "session_1730000000000",
  "output_basename": "mydata",
  "subject_prefix": "项目资料-分卷传输",
  "volume_size_mb": 20,
  "send_interval_sec": 5,
  "recipients": "a@x.com,b@x.com",
  "cc": "",
  "smtp_host": "smtp.qq.com",
  "smtp_port": 465,
  "smtp_username": "you@x.com",
  "smtp_password": "xxxx",
  "smtp_use_ssl": true,
  "smtp_use_tls": false
}
```

---

## 7z / 7zz 说明

- 首次启动，后端会从 `app/bin/*.tar.xz` 自动解包出 `7zz` 到 `{DATA_DIR}/7z/7zz` 并尝试 `chmod +x`
- 平台选择逻辑：
  - macOS → `7z2501-mac.tar.xz`
  - Linux x64 → `7z2501-linux-x64.tar.xz`
  - Linux ARM64 → `7z2501-linux-arm64.tar.xz`
- 如需手动指定包名：设置 `SEVENZ_TARBALL` 环境变量

---

## 日志与排错

- 服务运行日志：`{DATA_DIR}/logs/app.log`
- 常见问题：
  1. **SMTP 预检失败**：核对端口与 SSL/TLS（465=SSL、587=TLS、25=明文）；检查凭据及可达性  
  2. **上传慢/失败**：查看浏览器/网络与后端日志，注意大文件场景的反向代理限制（413）  
  3. **未生成分卷**：确认 `DEFAULT_VOLUME_SIZE_MB > 0`；检查 `7zz` 是否解包并可执行（`chmod +x`）

---

## 安全建议

- 前端默认**无鉴权**，建议仅在**内网/受限网段**使用或加反向代理鉴权  
- SMTP 凭据通过**环境变量**注入，避免持久化在代码库中

---

## 开发

```bash
pip install ruff black
ruff check app --fix
black app
```

- 后端：FastAPI + Pydantic  
- 前端：原生 HTML/CSS/JS（XHR 监听上传进度）  
- 日志：`/api/logs?job_id=` 轮询刷新

---

## 版本与协议

- 后端版本：**1.2.2**（`FastAPI(title="Folder Split-Mailer", version="1.2.2")`）  
- 文档更新：2025-08-26

License: MIT
