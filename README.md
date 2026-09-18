# ACM Nav

TOML 驱动的 ACM 集训队导航页。

## 部署

从 GitHub Release 下载 `acm-nav-v1.0.1.zip`（替换为实际版本号）并上传到 Linux 服务器。以下以 `/opt/acm-nav` 为部署目录；服务器只需要 Python 3.11+ 和 `python3-venv`：

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

如需由普通用户维护配置，将其加入服务组并授予配置目录写权限（将 `<用户名>` 替换为实际登录名）：

```bash
sudo usermod -aG acm-nav <用户名>
sudo chgrp acm-nav /opt/acm-nav /opt/acm-nav/config.toml
sudo chmod 2775 /opt/acm-nav
sudo chmod 664 /opt/acm-nav/config.toml
```

该用户重新登录后可直接编辑 `/opt/acm-nav/config.toml`；保存后网站自动热更新，无需重启服务。

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
| `type` | `"link"`（默认）或 `"info"` | `link` 为外部链接；`info` 为点击后弹出的公告。 |
| `icon` | 文件名，默认 `link.svg` | `frontend/public/icons/services/` 下的图标文件名；可省略 `.svg` 后缀。链接项目未填写时会尝试抓取网站图标，失败则使用 `link.svg`。 |
| `description` | 字符串，默认空 | 卡片说明；鼠标悬浮时显示。 |
| `url` | 字符串，默认空 | `type = "link"` 时必填，且必须是完整的 `http://` 或 `https://` 地址。 |
| `content` | 字符串，默认空 | `type = "info"` 时使用，支持 Markdown。 |

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

图标源文件放在 `frontend/public/icons/services/`；构建时会复制到 `frontend/static/`，该目录为 Git 忽略的构建产物。
