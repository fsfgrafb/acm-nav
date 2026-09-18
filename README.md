# ACM Nav

TOML 驱动的 ACM 集训队导航页。

## 部署

在开发机生成发布包：

```powershell
npm --prefix frontend ci
python build.py
```

将 `release/acm-nav.zip` 上传到 Linux 服务器。以下以 `/opt/acm-nav` 为部署目录；服务器只需要 Python 3.11+ 和 `python3-venv`：

```bash
sudo apt install python3 python3-venv unzip
sudo useradd --system --user-group --home /opt/acm-nav --shell /usr/sbin/nologin acm-nav
sudo mkdir -p /opt/acm-nav
sudo unzip acm-nav.zip -d /opt/acm-nav
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

- `[appearance]`：站点标题、英文抬头、页面描述。
- `[[sections]]`：页面区域；`title` 必须唯一。
- `[[sections.items]]`：链接或公告项。
- `[admin].ips`：允许显示管理员区域的 IP 地址。

图标源文件放在 `frontend/public/icons/services/`；构建时会复制到 `frontend/static/`，该目录为 Git 忽略的构建产物。
