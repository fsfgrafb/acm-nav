"""构建可搬到目标机器的源码运行包，不包含本机配置和统计。"""

import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent


def build():
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("请先安装 Node.js，并执行 npm --prefix frontend ci")
    subprocess.run([npm, "--prefix", str(ROOT / "frontend"), "run", "build"], check=True)
    output = ROOT / "release/acm-nav.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for folder in ("backend", "frontend/static"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(ROOT))
        for filename in ("requirements.txt", "README.md", "LICENSE"):
            archive.write(ROOT / filename, filename)
    print(f"已生成：{output}")


if __name__ == "__main__":
    build()
