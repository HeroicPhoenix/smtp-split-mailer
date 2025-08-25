# 📦 smtp-split-mailer

基于 **FastAPI + 7-Zip + SMTP** 的分卷压缩与批量邮件发送工具。  
支持将文件夹自动分卷压缩，并通过邮件逐个分卷发送，前端页面适配 PC 与手机端。  

---

## 🚀 功能特性
- 🌐 前端界面（浅色主题，适配移动端）
- 📂 文件夹上传（支持保持原始目录结构）
- 📦 自动分卷压缩（调用 7z，支持 Linux/macOS/x86/arm64）
- 📧 批量邮件发送（支持 SSL/TLS，自动等待间隔）
- ⚙️ 配置支持 Docker 环境变量 + config.yaml 双重来源
- 📝 日志持久化（简体中文，输出到 logs/app.log）
- 🐳 Docker & docker-compose 一键部署

---

## 📂 项目目录结构
```
smtp-split-mailer/
├── app/ # 应用主目录
│ ├── main.py # FastAPI 后端主程序
│ └── static/ # 前端页面
│ └── index.html
│
├── config/ # 配置目录
│ └── config.yaml # 默认配置文件
│
├── data/ # 数据目录（挂载点）
│ ├── 7z/ # 解压出的 7zz 可执行文件
│ │ └── 7zz
│ ├── bin/ # 存放 7z 压缩包（tar.xz）
│ │ ├── 7z2501-linux-arm64.tar.xz
│ │ ├── 7z2501-linux-x64.tar.xz
│ │ └── 7z2501-mac.tar.xz
│ ├── logs/ # 日志目录
│ ├── outputs/ # 压缩结果目录（按 session_id）
│ └── uploads/ # 上传文件目录（按 session_id）
│
├── docker-compose.yml # Docker Compose 配置
├── Dockerfile # Docker 镜像构建文件
├── requirements.txt # Python 依赖清单
└── README.md # 使用文档
```

---

## ⚙️ 环境变量配置（docker-compose）
在 `docker-compose.yml` 中通过 `environment` 配置：

```yaml
environment:
  # --- SMTP 配置 ---
  SMTP_HOST: "smtp.xxx.com"
  SMTP_PORT: 465
  SMTP_USERNAME: "yourname@xxx.com"
  SMTP_PASSWORD: "授权码或密码"
  SMTP_USE_SSL: "true"
  SMTP_USE_TLS: "false"

  # --- 默认值配置 ---
  DEFAULT_SENDER: "yourname@xxx.com"
  DEFAULT_RECIPIENTS: "a@xxx.com,b@xxx.com"
  DEFAULT_CC: "boss@xxx.com"
  DEFAULT_SUBJECT_PREFIX: "项目资料-分卷传输"
  DEFAULT_OUTPUT_BASENAME: "mydata"
  DEFAULT_VOLUME_SIZE_MB: 20
  DEFAULT_SEND_INTERVAL_SEC: 5

  # --- 可选：强制指定 7z 包（放到 /app/bin/） ---
  # SEVENZ_TARBALL: "7z2501-linux-x64.tar.xz"
```

---

## 🐳 Docker 部署

### 1. 构建镜像
```bash
docker build -t smtp-split-mailer .
```

### 2. 启动服务
```bash
docker-compose up -d
```

### 3. 访问服务
- 前端页面：http://localhost:12082  
- API 接口：http://localhost:12082/api  

---

## 💻 本地开发运行
```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 12082
```

---

## 📖 使用流程
1. 打开前端页面，上传需要压缩的文件夹
2. 系统会自动保存到 `uploads/session_xxx/`
3. 后端调用 7z 进行分卷压缩，结果存放到 `outputs/session_xxx/`
4. 启动邮件发送任务，逐封邮件发送带附件的压缩包
5. 邮件发送完成后可在日志中查看完整记录

---

## 📝 日志
- 输出路径：`logs/app.log`
- 说明：  
  - 前端：显示简化中文日志  
  - 文件：保存完整运行日志（包含压缩/发送详情）

---

## 🛠️ 注意事项
- **7z 安装包**请放到 `/app/bin`，支持：
  - `7z2501-linux-x64.tar.xz`
  - `7z2501-linux-arm64.tar.xz`
  - `7z2501-mac.tar.xz`
- **群晖部署**时，建议将以下目录映射到宿主机：
  - `/data` → `/volume1/docker/smtp-split-mailer/data`

---

## 📌 License
MIT License
