#!/usr/bin/env python3
"""终端守卫：对可能造成架构漂移或不可逆破坏的命令弹人工确认。

写入守卫只看得到文件工具，看不到 `mkdir backend` 这类绕道操作。本守卫补上这条缝。
一律返回 ask 而非 deny —— 这些命令在合法场景下确有用途，交人类当场判断即可。

挂在 beforeShellExecution 上，failClosed=false —— 守卫出错不应阻断正常开发。
"""

import json
import re
import sys

RISKY = [
    (r"\bmkdir\b", "创建新目录", "除 .streamlit/ 配置目录外，本项目禁止新建顶层目录（AGENTS.md 第 2 节）。确认这不是在造 frontend/ 或 backend/。"),
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+", "递归或强制删除", "递归删除不可逆，确认目标路径无误。"),
    (r"\bgit\s+push\b.*(--force|-f)\b", "强制推送", "强制推送会覆盖远端历史，可能抹掉队友的提交。"),
    (r"\bgit\s+reset\s+--hard\b", "硬重置", "硬重置会丢弃未提交的改动。"),
    (r"\bgit\s+(checkout|restore)\s+--\s", "丢弃工作区改动", "该命令会丢弃未提交的改动，无法撤销。"),
    (r"\bgit\s+clean\b", "清理未跟踪文件", "会删除未跟踪文件，可能包含尚未提交的语料或 .env。"),
    (r"\bgit\s+config\b", "修改 git 配置", "git 配置由人类掌管，智能体不得代改（AGENTS.md 第 6 节）。"),
    (r"\bmv\s+.*\b(main|app|config)\.py\b", "移动核心入口文件", "config.py 用自身位置推导数据目录，移动入口会静默打断 import 链。"),
    (r">\s*\.gitignore\b|>>\s*\.gitignore\b", "改写 .gitignore", ".gitignore 中 HPO-MCP-Server/、chroma_db/ 两条不得丢失。"),
    (r"\bpip\s+install\b(?!.*-r\s)", "临时安装依赖", "装完请同步更新 requirements.txt，否则队友环境会缺包。"),
]


def emit(permission, user_message=None, agent_message=None):
    out = {"permission": permission}
    if user_message:
        out["user_message"] = user_message
    if agent_message:
        out["agent_message"] = agent_message
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        emit("allow")

    command = payload.get("command") or payload.get("shell_command") or ""
    if not isinstance(command, str) or not command.strip():
        emit("allow")

    for pattern, label, reason in RISKY:
        if re.search(pattern, command):
            emit(
                "ask",
                f"终端守卫：这条命令涉及{label}。\n{reason}\n\n{command}",
                f"该命令被终端守卫标记为「{label}」。{reason}",
            )

    emit("allow")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # 守卫出错不应阻断正常开发
        print(json.dumps({"permission": "allow"}, ensure_ascii=False))
        sys.exit(0)
