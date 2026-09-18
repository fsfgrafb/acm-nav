"""配置即页面：区域与卡片使用同一套模型。"""

import ipaddress
import logging
import re
import tomlkit
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def local_path(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    # 同时拦截越界路径和指向目录外的符号链接。
    if not name or "\\" in name or ":" in name or not target.is_relative_to(root.resolve()):
        raise ValueError(f"非法相对路径：{name}")
    return target


def static_root(root: Path) -> Path:
    deployed_static = root / "static"
    return deployed_static if deployed_static.is_dir() else root / "frontend/dist"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Server(Model):
    host: str = "0.0.0.0"
    port: int = Field(default=80, ge=1, le=65535)


class Appearance(Model):
    title: str = "苏州工学院 ACM 集训队导航"
    kicker: str = "SZUT ACM Team"
    description: str = "校内服务与集训队信息"


class Admin(Model):
    ips: list[str] = Field(default_factory=lambda: ["127.0.0.1"])

    @field_validator("ips")
    @classmethod
    def valid_ips(cls, values):
        try:
            return [str(ipaddress.ip_address(value)) for value in values]
        except ValueError as exc:
            raise ValueError(f"非法设备 IP：{exc}") from exc


class Item(Model):
    name: str = Field(min_length=1)
    icon: str = "link.svg"
    description: str = ""
    type: Literal["link", "info", "resource"] = "link"
    url: str = ""
    content: str = ""

    @model_validator(mode="after")
    def check_content(self):
        parsed = urlsplit(self.url)
        http_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        resource_url = (
            bool(self.url)
            and not parsed.scheme
            and not parsed.netloc
            and "\\" not in self.url
            and all(part not in {"", ".", ".."} for part in parsed.path.split("/"))
        ) or (self.url.startswith("/resources/") and len(self.url) > len("/resources/"))
        if self.type == "link":
            if not http_url:
                raise ValueError("链接必须为有效的 HTTP(S) 地址")
        elif self.type == "resource" and not (http_url or resource_url):
            raise ValueError("资源必须使用 HTTP(S) 地址、资源文件名或 /resources/ 路径")
        elif self.type == "info" and self.url:
            if not (http_url or resource_url):
                raise ValueError("公告文件必须使用 HTTP(S) 地址、资源文件名或 /resources/ 路径")
            if Path(parsed.path).suffix.lower() not in {".md", ".markdown", ".txt"}:
                raise ValueError("公告文件必须是 Markdown 或 TXT 文件")
        return self

    @field_validator("icon")
    @classmethod
    def service_icon(cls, value):
        if value.startswith("/icons/services/"):
            name = value.removeprefix("/icons/services/")
            if name and all(part not in {"", ".", ".."} for part in name.split("/")):
                return value
        elif value and "/" not in value and "\\" not in value and ":" not in value:
            return value
        raise ValueError("图标必须是 services 下的文件名或 /icons/services/ 路径")


class Section(Model):
    title: str
    width: int = Field(default=2, ge=1, le=12)
    columns: int = Field(default=1, ge=1, le=6)
    visibility: Literal["public", "admin"] = "public"
    items: list[Item] = Field(default_factory=list)

class Config(Model):
    server: Server = Field(default_factory=Server)
    appearance: Appearance = Field(default_factory=Appearance)
    admin: Admin = Field(default_factory=Admin)
    sections: list[Section] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_section_titles(self):
        if len({section.title for section in self.sections}) != len(self.sections):
            raise ValueError("区域 title 不能重复")
        return self

def ensure_config(path: Path):
    if path.exists():
        return
    template = Path(__file__).with_name("default.toml").read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 独占创建，不覆盖部署机器上的配置。
        with path.open("x", encoding="utf-8") as file:
            file.write(template)
    except FileExistsError:
        return
    logging.getLogger("uvicorn.error").info("配置文件不存在，已创建默认配置：%s", path)


class IconLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None

    def handle_starttag(self, tag, attrs):
        if tag != "link" or self.href:
            return
        attributes = dict(attrs)
        if "icon" in attributes.get("rel", "").lower().split() and attributes.get("href"):
            self.href = attributes["href"]


def download_icon(url: str, name: str, directory: Path) -> str | None:
    if any(char in name for char in '<>:"/\\|?*') or name in {"", ".", ".."}:
        raise ValueError("自动下载图标时，卡片名称不能包含文件名保留字符")
    request = Request(url, headers={"User-Agent": "acm-nav/1.0"})
    try:
        with urlopen(request, timeout=5) as response:
            page = response.read(512 * 1024)
            content_type = response.headers.get_content_type()
            final_url = response.url
        parser = IconLinkParser()
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser.feed(page.decode("utf-8", errors="ignore"))
        icon_url = urljoin(final_url, parser.href) if parser.href else urljoin(final_url, "/favicon.ico")
        with urlopen(Request(icon_url, headers={"User-Agent": "acm-nav/1.0"}), timeout=5) as response:
            data = response.read(2 * 1024 * 1024 + 1)
            content_type = response.headers.get_content_type()
            final_url = response.url
        if len(data) > 2 * 1024 * 1024 or not content_type.startswith("image/"):
            return None
    except OSError:
        return None
    suffix = Path(urlsplit(final_url).path).suffix.lower()
    suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico"}.get(content_type, ".ico")
    filename = name + suffix
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(data)
    return filename


def read_config(
    path: Path, root: Path | None = None, download_icons: bool = False
) -> Config:
    original = path.read_text(encoding="utf-8-sig")
    document = tomlkit.parse(original)
    for section in document.get("sections", []):
        section.setdefault("width", 2)
        section.setdefault("columns", 1)
        for item in section.get("items", []):
            url = item.get("url")
            match = re.fullmatch(r"\[[^]]*\]\((https?://[^)]+)\)", url or "")
            if match:
                item["url"] = match.group(1)
            # 下载图标会访问网络，只能由后台任务显式触发，不能阻塞启动或热更新。
            if (
                download_icons
                and root
                and "icon" not in item
                and item.get("type", "link") == "link"
            ):
                filename = download_icon(item.get("url", ""), item.get("name", ""), static_root(root) / "icons/services")
                if filename:
                    item["icon"] = filename
    # 先验证整份配置，再回写，避免将无效编辑写回磁盘。
    result = Config.model_validate(document.unwrap())
    normalized = tomlkit.dumps(document)
    if normalized != original:
        # 编辑器保存期间不覆盖更新的内容；下一次扫描会重试。
        if path.read_text(encoding="utf-8-sig") != original:
            raise ValueError("配置正在保存，稍后重试")
        path.write_text(normalized, encoding="utf-8")
    return result


def load_site(path: Path, root: Path) -> dict:
    data = read_config(path, root).model_dump(exclude={"server"}, by_alias=True)
    for section in data["sections"]:
        for item in section["items"]:
            if item["icon"]:
                icon = item["icon"].removeprefix("/icons/") if item["icon"].startswith("/icons/") else f"services/{item['icon']}"
                if not local_path(static_root(root) / "icons", icon).is_file():
                    item["error"] = "文件不存在"
    return data
