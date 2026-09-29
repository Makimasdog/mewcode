"""危险命令检测（五层权限体系的第 1、1b 层用到的能力）。

本文件提供两类"命令安全"工具：
1. DangerousCommandDetector —— 用正则黑名单识别危险命令（如删除根目录）。
2. is_safe_command()        —— 判断命令是否是"安全的只读命令"，决定能否直接放行。
"""
from __future__ import annotations

import re

# 危险命令黑名单：每项是 (正则表达式, 触发时显示原因)
# 只要命令匹配到任一表达式，就认为有危险。注意末尾用 \s*$ 限制，避免误伤普通命令。
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\s*$"), "递归强制删除根目录"),
    (re.compile(r"mkfs\."), "格式化磁盘"),
    (re.compile(r"dd\s+if=.*of=/dev/"), "直接写磁盘设备"),
    (re.compile(r"chmod\s+-R\s+777\s+/"), "递归修改根目录权限"),
    (re.compile(r":\(\)\{\s*:\|:&\s*\};:"), "fork bomb"),
    (re.compile(r"curl\s+.*\|\s*(ba)?sh"), "管道执行远程脚本"),
    (re.compile(r"wget\s+.*\|\s*(ba)?sh"), "管道执行远程脚本"),
    (re.compile(r">\s*/dev/sd"), "覆盖磁盘设备"),
]


# 安全命令白名单：这些命令（或以其开头的命令）被视为"只读、无副作用"，可直接放行。
# 用 frozenset 不可变，防止被意外修改。
_SAFE_COMMANDS = frozenset({
    "ls", "dir", "pwd", "echo", "cat", "head", "tail", "wc",
    "find", "which", "whereis", "whoami", "hostname", "uname",
    "date", "cal", "uptime", "df", "du", "free", "env", "printenv",
    "file", "stat", "readlink", "realpath", "basename", "dirname",
    "sort", "uniq", "tr", "cut", "awk", "sed", "grep", "egrep", "fgrep",
    "diff", "comm", "tee", "xargs", "true", "false", "test",
    # git 系列只读子命令（git status/log/diff...）
    "git status", "git log", "git diff", "git show", "git branch",
    "git tag", "git remote", "git rev-parse", "git ls-files",
    "git blame", "git stash list", "go version", "go env",
    "node -v", "npm -v", "npx", "python --version", "pip list",
    "cargo --version", "rustc --version", "java -version", "java --version",
})


def is_safe_command(command: str) -> bool:
    """判断命令是否是安全只读命令（PermissionChecker 第 1 层用它做自动放行）。

    两条防线必须都通过才算安全：
    1. 不能包含管道/链接符等会"串联操作"的符号（| ; && > $( `）；
    2. 命令本身（连同参数前缀）必须在白名单里。
    """
    trimmed = command.strip()
    if not trimmed:
        return False
    # 防线一：出现这些符号说明命令做了复杂串联，一律不安全
    for ch in ("|", ";", "&&", ">", "$(", "`"):
        if ch in trimmed:
            return False
    # 防线二：整条命令或"命令+空格开头"必须在白名单内
    for safe in _SAFE_COMMANDS:
        if trimmed == safe or trimmed.startswith(safe + " "):
            return True
    return False


class DangerousCommandDetector:
    """用正则黑名单识别危险命令（PermissionChecker 第 1b 层用它拦截）。

    check() 会把命令和 _patterns 里所有正则逐一比对，命中任一即判定为危险。
    """


    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None) -> None:
        """初始化：复制内置黑名单，并允许调用方额外追加自定义危险模式。

        :param extra_patterns: 可选的自定义规则，每项 (正则字符串, 原因)。
                              例如 ("scp .* @evil", "向恶意服务器发送文件")。
        """
        self._patterns = list(_DANGEROUS_PATTERNS)
        if extra_patterns:
            for regex_str, reason in extra_patterns:
                # 用户给的是字符串，先编译成 Pattern 再统一存进列表
                self._patterns.append((re.compile(regex_str), reason))


    def detect(self, command: str) -> tuple[bool, str]:
        """检查一条命令是否命中危险黑名单。

        :return: (是否危险, 触发原因)。安全时 reason 为空字符串。
        """
        for pattern, reason in self._patterns:
            if pattern.search(command):
                return True, reason
        return False, ""