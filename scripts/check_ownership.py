"""按分支名校验本次提交是否越过了轨道边界。

这是多智能体协作的第三层防线。前两层（.cursor/rules 软约束、.cursor/hooks 工具层拦截）
都作用于「智能体正在写」的那一刻；本脚本作用于提交时，负责捕捉漏网的跨轨改动——
典型场景是前端智能体顺手改了 main.py，或后端智能体"帮忙"调了 app.py 的渲染。

分支名即轨道身份：

    feat/fe-*    前端轨   只许动 app.py 与 .streamlit/config.toml
    feat/be-*    后端轨   只许动 main.py
    feat/rag-*   知识轨   只许动 scripts/**
    其余分支                不限（人类与基建轨）

用法：
    python scripts/check_ownership.py            # 校验已暂存的改动（pre-commit 用）
    python scripts/check_ownership.py --worktree # 校验工作区全部改动，提交前自查

全部合规退出码 0，有越界退出码 1。
"""

import argparse
import fnmatch
import subprocess
import sys

# 分支前缀 -> (轨道名, 允许改动的路径模式)
TRACKS = [
    ("feat/fe-", "前端轨", ["app.py", ".streamlit/config.toml"]),
    ("feat/be-", "后端轨", ["main.py"]),
    ("feat/rag-", "知识轨", ["scripts/*"]),
]

# 任何轨道都不得直接提交的共享事实来源，改动须走 main 或 feat/infra-* 分支并经人工评审。
SHARED = ["config.py", "docs/*", "data/knowledge/*", ".gitignore", ".env.example", "requirements.txt"]


def git(*args):
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def matches_any(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def main():
    parser = argparse.ArgumentParser(description="按分支名校验文件所有权")
    parser.add_argument(
        "--worktree",
        action="store_true",
        help="校验工作区全部改动而非仅暂存区",
    )
    args = parser.parse_args()

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        print("check_ownership: 不在 git 仓库内，跳过校验。")
        return 0

    if args.worktree:
        changed = git("diff", "--name-only", "HEAD")
    else:
        changed = git("diff", "--cached", "--name-only")

    files = [f for f in (changed or "").splitlines() if f.strip()]
    if not files:
        return 0

    track = next((t for t in TRACKS if branch.startswith(t[0])), None)
    if track is None:
        print(f"check_ownership: 分支 `{branch}` 不受轨道约束，跳过校验。")
        return 0

    _, track_name, allowed = track
    violations = [f for f in files if not matches_any(f, allowed)]

    if not violations:
        print(f"check_ownership: {track_name}（{branch}）{len(files)} 个文件均在所有权范围内。")
        return 0

    print(f"\n提交被拦截：当前分支 `{branch}` 属于{track_name}，只允许改动 {'、'.join(allowed)}。\n")
    print("以下文件越界：")
    for f in violations:
        tag = "共享事实来源，须经人工评审" if matches_any(f, SHARED) else "属于其他轨道"
        print(f"  - {f}    （{tag}）")

    print("\n处理方式（三选一）：")
    print("  1. 把越界文件的改动 unstage，交回它的属主轨道去做：")
    print(f"       git restore --staged {' '.join(violations)}")
    print("  2. 这确实是基建类改动 —— 换到不受约束的分支：")
    print("       git switch -c feat/infra-<描述>")
    print("  3. 你确认这是必要的跨轨改动，本次放行：")
    print("       git commit --no-verify")
    print("\n所有权表见 AGENTS.md 第 1 节。\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
