#!/usr/bin/env python3
"""写入守卫：在工具调用前拦截越界的文件写入。

规则层（.cursor/rules/）只是进入模型上下文的软约束，模型可能忽略。本守卫在工具层裁决，
模型绕不过去，是「禁止发明不存在的文件夹」这条宪法的唯一硬保障。

裁决依据 .cursor/hooks/allowlist.json：
    writable  -> allow   智能体日常可写（main.py / app.py / scripts/*.py 等）
    confirm   -> ask     共享事实来源，改动须人类点头（config.py / docs / data 等）
    其余       -> deny    白名单外路径，直接拒绝

挂在 preToolUse 上，failClosed=true —— 守卫自身出错时宁可挡住写入，也不放行未经裁决的路径。
"""

import json
import sys
from pathlib import Path, PurePosixPath

HOOK_DIR = Path(__file__).resolve().parent
ALLOWLIST = HOOK_DIR / "allowlist.json"
# 脚本固定位于 <工作区根>/.cursor/hooks/，据此反推根目录，不依赖 hook 载荷字段。
FALLBACK_ROOT = HOOK_DIR.parent.parent

# 只对写入类工具生效，读取与检索一律放行。
WRITE_TOOLS = {"write", "stredit", "strreplace", "edit", "multiedit", "delete", "editnotebook"}

# 递归扫描 payload 时，视为「文件路径」的键名。
PATH_KEYS = {
    "path", "filepath", "file", "targetfile", "abspath",
    "relativepath", "notebookpath", "targetnotebook", "newpath", "oldpath",
}


def emit(permission, user_message=None, agent_message=None):
    out = {"permission": permission}
    if user_message:
        out["user_message"] = user_message
    if agent_message:
        out["agent_message"] = agent_message
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def normalize_key(key):
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def collect_paths(node, found):
    """递归收集 payload 里所有路径值。工具的入参结构可能变化，故不写死字段名。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and normalize_key(key) in PATH_KEYS:
                found.append(value)
            else:
                collect_paths(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_paths(item, found)


def resolve_root(payload):
    """取工作区根。载荷字段名不保证稳定，故以脚本自身位置为兜底。"""
    candidate = payload.get("workspace_root") or payload.get("workspaceRoot")
    if not candidate:
        roots = payload.get("workspace_roots") or payload.get("workspaceRoots")
        if isinstance(roots, list) and roots:
            candidate = roots[0]
    if not candidate:
        candidate = FALLBACK_ROOT
    return PurePosixPath(str(candidate).replace("\\", "/").rstrip("/"))


def to_relative(raw, root):
    """把绝对或相对路径统一成相对工作区根的 POSIX 路径。越界返回 None。"""
    path = PurePosixPath(str(raw).replace("\\", "/"))
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None
    parts = [p for p in path.parts if p not in (".", "")]
    if any(p == ".." for p in parts):
        return None
    return PurePosixPath(*parts) if parts else None


def matches(rel, pattern):
    """支持两种模式：`dir/**` 前缀匹配，以及 PurePath.match 的单层通配。"""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return str(rel) == prefix or str(rel).startswith(prefix + "/")
    return rel.match(pattern)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        emit("allow")

    tool = normalize_key(payload.get("tool_name") or payload.get("toolName") or "")
    if tool and tool not in WRITE_TOOLS:
        emit("allow")

    root = resolve_root(payload)

    try:
        rules = json.loads(open(ALLOWLIST, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError) as exc:
        emit("ask", f"写入守卫无法读取白名单 {ALLOWLIST}：{exc}", "白名单文件损坏，请人工确认后再写入。")

    writable = rules.get("writable", [])
    confirm = rules.get("confirm", [])
    forbidden_dirs = set(rules.get("forbidden_dirs", []))

    found = []
    collect_paths(payload, found)
    if not found:
        emit("allow")

    for raw in found:
        rel = to_relative(raw, root)
        if rel is None:
            emit(
                "deny",
                f"写入守卫拦截：目标路径超出工作区范围（{raw}）。",
                "该路径不在工作区内。请只写入 .cursor/hooks/allowlist.json 列出的文件。",
            )

        top = rel.parts[0] if rel.parts else ""
        if top in forbidden_dirs:
            emit(
                "deny",
                f"写入守卫拦截：`{top}/` 是被宪法禁止的目录名（{rel}）。",
                f"本项目是根目录单体，不是 monorepo。禁止创建 `{top}/`。"
                "后端写根目录 main.py，前端写根目录 app.py。详见 AGENTS.md 第 2 节。",
            )

        if any(matches(rel, p) for p in writable):
            continue

        if any(matches(rel, p) for p in confirm):
            emit(
                "ask",
                f"`{rel}` 是共享事实来源（人类属主），智能体正请求修改它。",
                f"`{rel}` 属于共享只读区。若确有必要改动，请先向人类说明理由。",
            )

        emit(
            "deny",
            f"写入守卫拦截：`{rel}` 不在允许写入的文件清单内。",
            f"`{rel}` 不在 .cursor/hooks/allowlist.json 中。禁止凭空创建新文件或新目录——"
            "先确认现有文件里是否已有该功能的归属；确需新增，请向人类申请把路径加入白名单。",
        )

    emit("allow")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # 守卫自身崩溃时不静默放行
        print(json.dumps({
            "permission": "ask",
            "user_message": f"写入守卫执行异常：{exc}",
            "agent_message": "写入守卫异常，请人工确认本次写入是否越界。",
        }, ensure_ascii=False))
        sys.exit(0)
