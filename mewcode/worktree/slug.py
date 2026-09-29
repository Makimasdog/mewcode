"""
slug.py — Worktree 名称验证与扁平化
=====================================

【这个模块做什么】
处理 worktree 名称的验证和转换。

【什么是 Slug】
Slug 是 worktree 的标识符，支持 "/" 分层命名（如 "feature/login"）。
但文件系统不支持 "/" 作为目录名，所以需要扁平化：
    "feature/login" → flatten → "feature+login"

对应的 Git 分支名：
    worktree-feature+login

【命名规则】
- 最长 64 字符
- 每段只能包含字母、数字、.、-、_
- 不允许空段、. 或 .. 作为段（防止路径穿越）
"""

from __future__ import annotations

import re

MAX_SLUG_LENGTH = 64
# 合法段字符：字母、数字、点、连字符、下划线
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(name: str) -> str | None:
    """
    验证 worktree 名称是否合法。
    
    返回:
        None: 名称合法
        str: 错误消息（名称不合法）
    """
    if not name:
        return "name cannot be empty"
    if len(name) > MAX_SLUG_LENGTH:
        return f"name too long (max {MAX_SLUG_LENGTH} characters)"


    segments = name.split("/")
    for seg in segments:
        if not seg:
            return "name contains empty segment"
        if seg in (".", ".."):
            return "name must not contain '.' or '..' as a segment"
        if not _SEGMENT_RE.match(seg):
            return f"invalid segment: {seg!r} (allowed: letters, digits, '.', '-', '_')"


    return None


def flatten_slug(name: str) -> str:
    """
    将分层名称扁平化为文件系统安全的字符串。
    
    将 "/" 替换为 "+"，用于生成目录名和分支名。
    例如："feature/login" → "feature+login"
    """
    return name.replace("/", "+")
