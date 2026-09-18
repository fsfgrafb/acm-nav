# ACM Nav

TOML 驱动的 ACM 集训队导航页。

## 部署

从 GitHub Release 下载 `acm-nav-v1.0.1.zip`（替换为实际版本号）并上传到 Linux 服务器。以下以 `/opt/acm-nav` 为部署目录；服务器只需要 Python 3.11+ 和 `python3-venv`。`/opt/acm-nav` 只是示例，程序不会硬编码该路径：可替换为任意绝对安装目录，程序会以包含 `backend/`、`frontend/`、`static/` 的 `acm-nav` 根目录为准。

```bash
sudo apt install python3 python3-venv unzip
sudo useradd --system --user-group --home /opt/acm-nav --shell /usr/sbin/nologin acm-nav
sudo mkdir -p /opt/acm-nav
sudo unzip acm-nav-v1.0.1.zip -d /opt/acm-nav
sudo chown -R acm-nav:acm-nav /opt/acm-nav
sudo -u acm-nav python3 -m venv /opt/acm-nav/.venv
sudo -u acm-nav /opt/acm-nav/.venv/bin/pip install -r /opt/acm-nav/requirements.txt
```

直接写入并启用 systemd 服务：

```bash
sudo tee /etc/systemd/system/acm-nav.service > /dev/null <<'EOF'
[Unit]
Description=ACM Nav
After=network.target

[Service]
User=acm-nav
Group=acm-nav
WorkingDirectory=/opt/acm-nav
ExecStart=/opt/acm-nav/.venv/bin/python -m backend.main
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now acm-nav && sudo systemctl status acm-nav
```

首次启动会创建 `/opt/acm-nav/config.toml`。默认访问地址为 `http://服务器 IP/`。

部署后的目录结构如下：

```text
/opt/acm-nav/
├── backend/                 # 后端代码
├── frontend/                # 前端页面：HTML、CSS、JS
└── static/                  # 图标与资源文件
    ├── icons/services/      # 链接图标
    ├── icons/site/          # 网站图标
    └── resources/           # 下载资源、Markdown 与 TXT 公告
        └── assets/          # Markdown 公告引用的图片
```

如需由普通用户维护配置和静态资源，应让该用户成为 `config.toml` 与 `static/` 的属主。服务仍通过 `acm-nav` 组读取配置、访问图标和资源。先指定维护用户名：

```bash
ACM_NAV_MAINTAINER="acm"  # 替换为实际登录名
sudo chown "$ACM_NAV_MAINTAINER":acm-nav /opt/acm-nav/config.toml
sudo chmod 664 /opt/acm-nav/config.toml

sudo chown -R "$ACM_NAV_MAINTAINER":acm-nav /opt/acm-nav/static
sudo find /opt/acm-nav/static -type d -exec chmod 2775 {} +
sudo find /opt/acm-nav/static -type f -exec chmod 664 {} +
```

## 更新

以下示例将已部署的站点更新至 `v1.0.3`。发布包不会包含 `config.toml`，但仍会在更新前覆盖保存一份 `config.toml.bak`，便于意外时恢复：

```bash
sudo systemctl stop acm-nav
sudo cp -a /opt/acm-nav/config.toml /opt/acm-nav/config.toml.bak
sudo unzip -o acm-nav-v1.0.3.zip -d /opt/acm-nav
sudo -u acm-nav /opt/acm-nav/.venv/bin/pip install -r /opt/acm-nav/requirements.txt
sudo systemctl start acm-nav
sudo systemctl status acm-nav
```

后续版本只需将压缩包文件名替换为对应版本号。确认网站正常后，可按需保留或删除 `/opt/acm-nav/config.toml.bak`。

## 卸载

仅移除 systemd 服务、保留程序与配置文件：

```bash
sudo systemctl disable --now acm-nav
sudo rm -f /etc/systemd/system/acm-nav.service
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

如需彻底删除程序、虚拟环境和配置，请先将下面的安装目录改为实际路径并确认无误；第二段命令不可恢复。建议先备份 `config.toml`：

```bash
APP_DIR="/opt/acm-nav"  # 替换为实际安装目录
sudo cp -a "$APP_DIR/config.toml" "$APP_DIR.config.toml.bak"
```

```bash
APP_DIR="/opt/acm-nav"  # 替换为实际安装目录
sudo rm -rf -- "$APP_DIR"
sudo userdel acm-nav
```

如果 `acm-nav` 用户或组还被其他服务使用，请跳过最后一条 `userdel`。

## 开发

Windows 上安装 Python 3.11+ 和 Node.js 后，在 PowerShell 依次执行：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python -m backend.main
```

打开 `http://127.0.0.1/`。

## 配置

编辑根目录的 `config.toml`，保存后页面会自动更新。完整示例见 `backend/default.toml`。

### 顶层配置

| 区块 | 字段 | 说明 |
| --- | --- | --- |
| `[server]` | `host` | 监听地址，默认 `0.0.0.0`。 |
| `[server]` | `port` | 监听端口，范围 `1`–`65535`，默认 `80`。 |
| `[appearance]` | `title` | 网站标题，同时用于浏览器标题。 |
| `[appearance]` | `kicker` | 标题上方的英文小标题。 |
| `[appearance]` | `description` | 页面描述（HTML meta description）。 |
| `[admin]` | `ips` | IP 字符串列表；访问者 IP 位于其中时，才显示管理员区域。默认仅 `127.0.0.1`。 |

### 页面区域：`[[sections]]`

每个区域支持以下字段，且 `title` 在整份配置中必须唯一。

| 字段 | 类型／默认值 | 说明 |
| --- | --- | --- |
| `title` | 字符串，必填 | 区域标题。 |
| `width` | 整数，默认 `2` | 区域在一行中占用的宽度分母，范围 `1`–`12`；例如 `width = 1` 占满一行，`width = 2` 占半行。 |
| `columns` | 整数，默认 `1` | 区域内卡片列数，范围 `1`–`6`。 |
| `visibility` | `"public"`（默认）或 `"admin"` | `public` 对所有访客显示；`admin` 仅在访问者 IP 命中 `[admin].ips` 时显示。 |

### 区域项目：`[[sections.items]]`

项目可为外部链接或站内公告，由 `type` 决定。

| 字段 | 类型／默认值 | 适用类型与说明 |
| --- | --- | --- |
| `name` | 字符串，必填 | 卡片名称。 |
| `type` | `"link"`（默认）、`"info"` 或 `"resource"` | `link` 为外部链接；`info` 为点击后弹出的公告；`resource` 为打开资源文件。 |
| `icon` | 文件名，默认 `link.svg` | 简写如 `link.svg` 对应 `static/icons/services/link.svg`；也可写完整网页路径 `/icons/services/link.svg`。链接项目未填写时会先读取网页声明的图标，未声明则请求 `/favicon.ico`；抓取失败则使用 `link.svg`。 |
| `description` | 字符串，默认空 | 卡片说明；鼠标悬浮时显示。 |
| `url` | 字符串，默认空 | `link` 必填，且必须是完整 HTTP(S) 地址。`resource` 必填；简写如 `a.exe` 对应 `static/resources/a.exe`，也可使用 HTTP(S) 或 `/resources/a.exe`。`info` 可选；填写时必须指向 HTTP(S)、资源文件名或 `/resources/` 下的 `.md`、`.markdown`、`.txt` 文件。 |
| `content` | 字符串，默认空 | `type = "info"` 时使用，支持 Markdown；若设置了 `url`，则加载该文件内容。 |

路径简写示例：

```toml
# static/icons/services/a.svg
icon = "a.svg"
# 与上一行等价
icon = "/icons/services/a.svg"

# type = "info"：static/resources/a.md
url = "a.md"
# type = "resource"：static/resources/a.exe
url = "a.exe"
# 资源完整网页路径
url = "/resources/a.exe"
```

示例：

```toml
[[sections]]
title = "内部服务"
width = 2
columns = 2
visibility = "admin"

[[sections.items]]
name = "运维公告"
type = "info"
description = "仅管理员可见"
content = "# 通知\n\n这里支持 **Markdown**。"
```

图标源文件放在 `frontend/public/icons/services/`；构建时会复制到根目录的 `static/icons/services/`，该目录为 Git 忽略的构建产物。
