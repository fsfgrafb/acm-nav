"""文件快照 + SSE；访客权限在服务端过滤。"""

import asyncio
import hashlib
import html
import ipaddress
import json
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .config import (
    Server, ensure_config, frontend_root, load_site, local_path, read_config, static_root,
)

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("uvicorn.error")
NO_CACHE = {"Cache-Control": "no-store"}


def initial_document(template: str, data: dict) -> str:
    """首屏标题直接随 HTML 返回，React 接管后继续使用同一份请求快照。"""
    site = data.get("site")
    header = ""
    if site:
        appearance = {key: html.escape(value, quote=True) for key, value in site["appearance"].items()}
        revision = html.escape(data["revision"], quote=True)
        ip = html.escape(data.get("current_ip") or "", quote=True)
        header = f'''<header class="site-header page-shell">
          <div class="brand">
            <span class="brand-mark"><img src="/icons/site/logo.svg?v={revision}" alt="" decoding="async"></span>
            <div class="brand-copy"><span class="brand-kicker">{appearance["kicker"]}</span><h1>{appearance["title"]}</h1>
              <span class="site-meta"><span class="visit-count">访问量：{data["visit_count"]}</span>{f'<span class="current-ip">{ip}</span>' if ip else ''}</span>
            </div>
          </div>
          <button class="theme-toggle" aria-label="切换为深色模式" title="切换为深色模式">
            <img src="/icons/site/sun.svg?v={revision}" alt="" decoding="async">
          </button>
        </header>'''
        template = template.replace('<title></title>', f'<title>{appearance["title"]}</title>')
        template = template.replace('name="description" content=""', f'name="description" content="{appearance["description"]}"')
        template = template.replace('<link rel="icon" />', f'<link rel="icon" href="/icons/site/favicon.svg?v={revision}" />')
    # script 元素内的 JSON 必须转义 <，防止公告中的 </script> 提前结束标签。
    snapshot = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    initial = f'''<div id="root"><div class="ambient ambient-one" aria-hidden="true"></div><div class="ambient ambient-two" aria-hidden="true"></div>{header}</div>
    <script id="site-snapshot" type="application/json">{snapshot}</script>
    <script>if (document.documentElement.dataset.theme === 'dark') {{
      const button = document.querySelector('.theme-toggle');
      if (button) {{ button.title = button.ariaLabel = '切换为浅色模式'; button.querySelector('img').src = '/icons/site/moon.svg?v={data['revision']}'; }}
    }}</script>'''
    return template.replace('<div id="root"></div>', initial)


def fingerprint(paths: list[Path]) -> tuple:
    # 只读取元数据，大型下载文件也不会反复读入内存。
    entries = []
    for root in paths:
        for path in [root] if not root.is_dir() else root.rglob("*"):
            try:
                if path.is_file():
                    stat = path.stat()
                    entries.append(
                        (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    )
            except OSError:
                pass  # 上传或替换中的文件留待下一轮。
    return tuple(sorted(entries))


class LiveSite:
    def __init__(self, root: Path, config: Path):
        self.root, self.config = root, config
        self.site = None
        self.error = None
        self.revision = 0
        self.build = ""
        self.changed = asyncio.Condition()
        self.icon_download = None

    def refresh(self):
        try:
            self.site = load_site(self.config, self.root)
            self.error = None
        except (ValueError, OSError) as exc:
            # 错误配置不会替换上一份有效内容。
            self.error = str(exc)
            log.warning("配置更新未应用：%s", exc)
        self.revision = time.time_ns()
        output = frontend_root(self.root)
        files = [output / "index.html", *(output / "assets").rglob("*.js")]
        self.build = hashlib.sha256(repr(fingerprint(files)).encode()).hexdigest()[:16]

    def queue_icon_download(self):
        """Fetch missing link icons without delaying application startup or reloads."""
        if self.icon_download and not self.icon_download.done():
            return

        async def download():
            try:
                # 配置先正常加载，缺失图标再由后台补齐。
                await asyncio.to_thread(read_config, self.config, self.root, True)
            except (ValueError, OSError) as exc:
                log.warning("图标下载未完成：%s", exc)

        self.icon_download = asyncio.create_task(download())

    def payload(self, admin=False, current_ip=None):
        # 只构造响应外层；不修改配置，也不复制只读的卡片内容。
        site = None if self.site is None else {
            "appearance": self.site["appearance"],
            "sections": [
                section for section in self.site["sections"]
                if admin or section["visibility"] == "public"
            ],
        }
        return {
            "revision": str(self.revision),
            "site": site,
            "stale": bool(self.error),
            "build": self.build,
            # 只返回当前请求的连接 IP，管理员名单本身不下发。
            "current_ip": current_ip,
        }

    async def watch(self):
        paths = list(dict.fromkeys([self.config, frontend_root(self.root), static_root(self.root)]))
        previous = await asyncio.to_thread(fingerprint, paths)
        self.refresh()
        self.queue_icon_download()
        while True:
            await asyncio.sleep(0.5)
            current = await asyncio.to_thread(fingerprint, paths)
            if current == previous:
                continue
            # 等到文件连续两次稳定，再发布；兼容编辑器原子保存。
            await asyncio.sleep(0.2)
            stable = await asyncio.to_thread(fingerprint, paths)
            if current != stable:
                continue
            previous = stable
            await asyncio.to_thread(self.refresh)
            self.queue_icon_download()
            async with self.changed:
                self.changed.notify_all()


class VisitCounter:
    """Keep the page-view count in memory and periodically checkpoint it."""

    def __init__(self, path: Path):
        self.path = path
        self.count = 0

    def restore(self):
        try:
            value = int(self.path.read_text(encoding="utf-8").strip())
            if value < 0:
                raise ValueError("访问量不能为负数")
            self.count = value
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("访问量文件读取失败，将从 0 开始：%s", exc)

    def visit(self):
        self.count += 1

    def save(self):
        """Atomically replace the checkpoint so an interrupted write keeps the old one."""
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                output.write(f"{self.count}\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            log.warning("访问量保存失败：%s", exc)
            with suppress(OSError):
                temporary.unlink()

    async def checkpoint(self):
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(self.save)


def create_app(root: Path = ROOT, config: Path | None = None) -> FastAPI:
    config = (
        config
        or Path(os.environ.get("NAVIGATOR_CONFIG", root / "config.toml")).resolve()
    )
    live = LiveSite(root, config)
    visits = VisitCounter(root / "visit_count.txt")

    @asynccontextmanager
    async def lifespan(app):
        ensure_config(config)
        await asyncio.to_thread(visits.restore)
        live.refresh()
        live.queue_icon_download()
        watcher = asyncio.create_task(live.watch())
        checkpoint = asyncio.create_task(visits.checkpoint())
        try:
            yield
        finally:
            tasks = [watcher, checkpoint]
            if live.icon_download:
                tasks.append(live.icon_download)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(visits.save)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.live = live
    app.state.visits = visits

    def request_ip(request: Request):
        if not request.client:
            return None
        # proxy_headers=False，始终使用与后端直接建连的对端 IP。
        try:
            return str(ipaddress.ip_address(request.client.host))
        except ValueError:
            return None

    def payload(request: Request):
        ip = request_ip(request)
        admin = bool(ip and live.site and ip in live.site["admin"]["ips"])
        data = live.payload(admin, ip)
        data["visit_count"] = visits.count
        return data

    @app.get("/api/site")
    async def site(request: Request):
        return JSONResponse(payload(request), headers=NO_CACHE)

    @app.get("/api/events")
    async def events(request: Request):
        visits.visit()

        async def stream():
            revision = None
            while True:
                # 先检查版本再等待，避免检查和订阅之间漏掉更新。
                async with live.changed:
                    if revision == live.revision:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(live.changed.wait(), 15)
                    revision = live.revision
                # 心跳时也重新检查权限，名单移除无需重新打开网页。
                yield (
                    "data: "
                    + json.dumps(payload(request), ensure_ascii=False)
                    + "\n\n"
                )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={**NO_CACHE, "X-Accel-Buffering": "no"},
        )

    def file(directory: Path, name: str):
        try:
            path = local_path(directory, name)
        except ValueError:
            raise HTTPException(404) from None
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(
            path, headers={**NO_CACHE, "X-Content-Type-Options": "nosniff"}
        )

    @app.get("/icons/{name:path}")
    async def icon(name: str):
        return file(static_root(root) / "icons", name)

    @app.get("/resources/{name:path}")
    async def resource(name: str):
        return file(static_root(root) / "resources", name)

    @app.get("/site.css")
    async def stylesheet():
        return file(frontend_root(root), "site.css")

    @app.get("/assets/{name:path}")
    async def asset(name: str):
        return file(frontend_root(root) / "assets", name)

    @app.get("/")
    async def index(request: Request):
        path = frontend_root(root) / "index.html"
        if not path.is_file():
            raise HTTPException(404)
        template = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return HTMLResponse(initial_document(template, payload(request)), headers=NO_CACHE)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config_path = Path(os.environ.get("NAVIGATOR_CONFIG", ROOT / "config.toml"))
    ensure_config(config_path)
    try:
        settings = read_config(config_path).server
    except (ValueError, OSError):
        # 首次配置损坏时仍启动，修正后自动恢复。
        settings = Server()
    uvicorn.run(
        "backend.main:app", host=settings.host, port=settings.port, proxy_headers=False
    )
