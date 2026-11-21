#!/usr/bin/env python3
"""
从 ROS2 工作空间下各包的 setup.py 里提取 install_requires，合并去重后写入 requirements 文件。
用法:
  python3 merge_setup_requires.py [src_dir ...] [-o OUTPUT]
默认: 扫描当前目录下的 src/，输出到 ./requirements-from-setuppy.txt
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def extract_install_requires(setup_py: Path) -> tuple[list[str], str | None]:
    """返回 (依赖列表, 错误说明)。依赖来自 setup(..., install_requires=[...]) 的字面量。"""
    try:
        source = setup_py.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(setup_py))
    except (OSError, SyntaxError) as e:
        return [], str(e)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name != "setup":
            continue
        for kw in node.keywords:
            if kw.arg != "install_requires" or kw.value is None:
                continue
            try:
                value = ast.literal_eval(kw.value)
            except (ValueError, TypeError):
                return [], "install_requires 不是静态字面量（如用了变量），跳过解析"
            if not isinstance(value, (list, tuple)):
                return [], "install_requires 不是 list/tuple"
            out: list[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
            return out, None
    return [], None


def find_setup_files(src_roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in src_roots:
        if not root.is_dir():
            continue
        files.extend(sorted(root.rglob("setup.py")))
    return files


def normalize_key(req: str) -> str:
    """用于去重：按包名小写（忽略版本标记的简单拆分）。"""
    base = req.split(";", 1)[0].strip()
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if sep in base:
            base = base.split(sep, 1)[0].strip()
            break
    return base.lower().replace("_", "-")


def main() -> int:
    parser = argparse.ArgumentParser(description="合并各 setup.py 的 install_requires")
    parser.add_argument(
        "src_dirs",
        nargs="*",
        default=["src"],
        type=Path,
        help="要扫描的 src 目录（可多个），默认: src",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("requirements-from-setuppy.txt"),
        help="输出文件路径，默认: requirements-from-setuppy.txt",
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    src_dirs_paths = [Path(d) for d in args.src_dirs]
    src_roots = [
        (cwd / d).resolve() if not d.is_absolute() else d.resolve()
        for d in src_dirs_paths
    ]
    setup_files = find_setup_files(src_roots)
    if not setup_files:
        print("未找到任何 setup.py，请检查 src 路径。", file=sys.stderr)
        return 1

    by_key: dict[str, str] = {}
    errors: list[tuple[Path, str]] = []

    for sp in setup_files:
        reqs, err = extract_install_requires(sp)
        if err:
            errors.append((sp, err))
            continue
        if not reqs:
            continue
        for r in reqs:
            k = normalize_key(r)
            if k not in by_key or len(r) > len(by_key[k]):
                by_key[k] = r

    lines = sorted(by_key.values(), key=str.lower)
    args.output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    print(f"扫描 setup.py 数量: {len(setup_files)}")
    print(f"合并后独立依赖数: {len(lines)}")
    print(f"已写入: {args.output.resolve()}")
    if errors:
        print(f"\n提示: {len(errors)} 个文件未解析到字面量 install_requires（可忽略若该包无 pip 依赖）:")
        for p, msg in errors[:15]:
            print(f"  - {p.relative_to(cwd) if p.is_relative_to(cwd) else p}: {msg}")
        if len(errors) > 15:
            print(f"  ... 另有 {len(errors) - 15} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())