# ACM Nav

TOML 驱动的 ACM 集训队导航页，支持链接、Markdown 公告、资源下载、深浅主题和按 IP 显示管理员区域。

## 部署

Linux 服务器需要 Python 3.11+。以下以 `/opt/acm-nav` 为安装目录，服务使用当前登录用户运行；更换目录时同步修改命令和 systemd 配置。

```bash
VERSION=v1.0.16
sudo apt install python3 python3-venv unzip curl
curl -fLO "https://github.com/fsfgrafb/acm-nav/releases/download/$VERSION/acm-nav-$VERSION.zip"
sudo mkdir -p /opt/acm-nav
sudo chown "$(id -un):$(id -gn)" /opt/acm-nav
unzip "acm-nav-$VERSION.zip" -d /opt/acm-nav
python3 -m venv /opt/acm-nav/.venv
/opt/acm-nav/.venv/bin/pip install -r /opt/acm-nav/requirements.txt
```

创建并启动服务：

```bash
sudo tee /etc/systemd/system/acm-nav.service > /dev/null <<EOF
[Unit]
Description=ACM Nav
After=network.target

[Service]
User=$(id -un)
Group=$(id -gn)
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
sudo systemctl daemon-reload
sudo systemctl enable --now acm-nav
sudo systemctl status acm-nav --no-pager
```

首次启动自动生成 `config.toml`，默认访问 `http://服务器IP/`。配置和资源归当前用户所有，可直接编辑。

## 更新

```bash
set -e
VERSION=v1.0.16
APP_DIR=/opt/acm-nav
curl -fLO "https://github.com/fsfgrafb/acm-nav/releases/download/$VERSION/acm-nav-$VERSION.zip"
unzip -tq "acm-nav-$VERSION.zip"
sudo systemctl stop acm-nav
rm -rf -- "$APP_DIR/frontend/assets"
unzip -o "acm-nav-$VERSION.zip" -d "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo systemctl start acm-nav
sudo systemctl status acm-nav --no-pager
```

## 配置

编辑根目录的 `config.toml`，保存后自动加载；无效配置不会替换上一份有效内容。监听地址和端口修改后需重启服务。示例见 [backend/default.toml](backend/default.toml)。

| 区块 | 字段 | 说明 |
| --- | --- | --- |
| `[server]` | `host`、`port` | 默认 `0.0.0.0:80`，端口范围 `1`–`65535`。 |
| `[appearance]` | `title`、`kicker`、`description` | 网站标题、英文小标题、页面元描述。 |
| `[admin]` | `ips` | 管理员 IP 列表，默认 `["127.0.0.1"]`；使用与后端直接连接的 IP。 |

每个 `[[sections]]` 定义一个区域：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `title` | 必填 | 区域标题，整份配置中唯一。 |
| `width` | `2` | 宽度分母，范围 `1`–`12`；`1` 为整行，`2` 为半行。 |
| `columns` | `1` | 卡片列数上限，范围 `1`–`6`，窄屏自动减少。 |
| `visibility` | `"public"` | `"admin"` 仅对管理员显示，集中在页面底部。 |

每个 `[[sections.items]]` 定义一张卡片：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `name` | 必填 | 卡片名称。 |
| `type` | `"link"` | `link` 外部链接、`info` 公告、`resource` 下载资源。 |
| `icon` | `info` 为 `"info.svg"`，其余为 `"link.svg"` | 图标文件名或 `/icons/services/` 下的路径；公告图标文件不存在时自动补为 `info.svg`。 |
| `description` | 空 | 卡片说明，悬浮或触屏时显示。 |
| `url` | 空 | `link` 必填 HTTP(S) 地址；`resource` 必填地址或资源文件名；`info` 可选 `.md`、`.markdown`、`.txt` 文件地址。 |
| `content` | 空 | 公告 Markdown 内容；填写 `url` 时优先读取文件。 |

链接图标未填写或文件不存在时，后台尝试抓取网页图标，失败则尝试 `/favicon.ico`；成功后将文件名写回配置。资源和公告支持 HTTP(S)、文件名简写或 `/resources/` 路径。

部署后的资源位置：

```text
static/
├── icons/services/    # icon = "a.svg" 对应这里的 a.svg
├── icons/site/        # Logo、主题按钮和 favicon
└── resources/         # url = "a.md" 对应这里的 a.md
```

## 开发

Windows PowerShell，需要 Python 3.11+ 和 Node.js 22.12+：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python -m backend.main
```

打开 `http://127.0.0.1/`。前端修改后重新构建。`frontend/public/` 会复制到 `frontend/dist/`；发布时将图标和资源移到 `static/`。本地存在 `static/` 时优先使用它，否则读取构建目录中的资源。

## 卸载

移除服务，保留程序和数据：

```bash
sudo systemctl disable --now acm-nav
sudo rm -f /etc/systemd/system/acm-nav.service
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

彻底卸载时，先备份 `config.toml`、`static/` 和 `visit_count.txt`，再删除实际安装目录。
