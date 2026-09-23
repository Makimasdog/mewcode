# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""权限检查器（五层安全防线）。

当 Agent 想调用某个工具前，PermissionChecker.check() 会逐层裁决：
到底该"放行""拒绝"，还是"请示用户"（ask）。五层从最特殊到最兜底，
像漏斗一样一层层过滤，每一层都可能在某个条件下直接给出结论并提前 return。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from mewcode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from mewcode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from mewcode.permissions.rules import RuleEngine, extract_content
from mewcode.permissions.sandbox import PathSandbox
from mewcode.tools.base import Tool

# Plan 模式下被允许的"安全工具"白名单（Agent / 提问 / 搜索这类辅助性工具）
_PLAN_MODE_ALLOWED_TOOLS = frozenset({"Agent", "ToolSearch", "AskUserQuestion", "ExitPlanMode"})


@dataclass
class Decision:
    """一次权限裁决的结论。凡被 `PermissionChecker.check()` 返回，即代表决策结果。

    - effect: 结果，取值为 "allow"（放行）/ "deny"（拒绝）/ "ask"（询问用户）
    - reason: 人类可读的原因，便于追踪"为什么这么判"
    """
    effect: DecisionEffect
    reason: str


class PermissionChecker:
    """组合多个安全组件，对单次工具调用做最终裁决。

    构造时注入四个"专业检查员"：
    - detector:     危险命令检测器（识别 rm -rf / 这类命令）
    - sandbox:      路径沙箱（防止访问项目目录外的敏感路径）
    - rule_engine:  规则引擎（用户自定义 allow/deny 规则）
    - mode:         权限模式（决定兜底策略，如 default/plan/bypassPermissions）
    """


    def __init__(
        self,
        detector: DangerousCommandDetector,
        sandbox: PathSandbox,
        rule_engine: RuleEngine,
        mode: PermissionMode = PermissionMode.DEFAULT,
    ) -> None:
        self.detector = detector
        self.sandbox = sandbox
        self.rule_engine = rule_engine
        self.mode = mode
        self.plan_file_path: str = ""  # Plan 模式下允许写入的文件路径


    def check(self, tool: Tool, arguments: dict[str, Any]) -> Decision:
        """对一个即将执行的工具调用做五层裁决，返回最终 Decision。

        :param tool: 要调用的工具（其 .name / .category 决定走哪些检查）
        :param arguments: 工具参数字典（从中提取被检查的"内容"，如文件路径或命令）
        """
        # 先抽取"被检查的目标内容"。不同工具取不同字段：
        # ReadFile 取 file_path，Bash 取 command，WriteFile 取 file_path。
        content = extract_content(tool.name, arguments)

        # Layer 0: Plan 模式例外放行
        # 处于 Plan 模式时，只允许"规划相关"的工具，或对规划文件本身的写操作。
        if self.mode == PermissionMode.PLAN:
            if tool.name in _PLAN_MODE_ALLOWED_TOOLS:
                return Decision(effect="allow", reason="Plan mode: allowed tool")
            if tool.name in ("WriteFile", "EditFile") and content:
                if self._is_plan_file(content):  # 只允许写规划文件
                    return Decision(effect="allow", reason="Plan mode: plan file write")

        # Layer 1: 安全的只读命令（自动放行）
        # 像 ls、git status 这类只读命令直接就放行，不打扰用户。
        if tool.category == "command" and is_safe_command(content or ""):
            return Decision(effect="allow", reason="Safe read-only command")

        # Layer 1b: 危险命令黑名单（仅 Bash）
        # 命令类工具若命中危险名单（如删除根目录），直接拒绝。
        if tool.category == "command":
            hit, reason = self.detector.detect(content)
            if hit:
                return Decision(effect="deny", reason=f"危险命令拦截: {reason}")

        # Layer 2: 路径沙箱（仅文件类工具）
        # read/write 类工具检查路径是否在项目沙箱内，越界则拒绝。
        if tool.category in ("read", "write") and content:
            ok, reason = self.sandbox.check(content)
            if not ok:
                return Decision(effect="deny", reason=f"路径沙箱拦截: {reason}")

        # Layer 3: 规则引擎匹配
        # 用户可在配置里写自定义规则（如"允许 git*"，或"拒绝 *.env"）。
        # 规则有最高优先级：命中则直接按规则结论执行。
        rule_result = self.rule_engine.evaluate(tool.name, content)
        if rule_result == "allow":
            return Decision(effect="allow", reason="权限规则放行")
        if rule_result == "deny":
            return Decision(effect="deny", reason="权限规则拒绝")

        # Layer 4: 权限模式兜底判定
        # 前面几层都没拦截也没放行时，由"权限模式"给出兜底结论。
        # 例如 bypassPermissions 模式全部放行、default 模式较宽松等。
        effect = mode_decide(self.mode, tool.category)
        if effect == "allow":
            return Decision(effect="allow", reason=f"权限模式 {self.mode.value} 放行")
        if effect == "deny":
            return Decision(effect="deny", reason=f"权限模式 {self.mode.value} 拒绝")

        # Layer 5: 触发人工确认（HITL / Human in the Loop）
        # 走到这里说明没有组件能明确决定，于是把控制权交回用户确认。
        return Decision(effect="ask", reason="需要用户确认")


    def _is_plan_file(self, target_path: str) -> bool:
        """判断某路径是否是 Plan 模式下允许写入的"规划文件"。

        满足任一条件即视为规划文件：
        - 位于 .mewcode/plans/ 目录下；
        - 与已登记的 plan_file_path 绝对路径一致；
        - 文件名与 plan_file_path 同名。
        """
        if not self.plan_file_path or not target_path:
            # 没登记具体规划文件时，宽松地看目录前缀即可
            return ".mewcode/plans/" in target_path
        try:
            abs_target = os.path.abspath(target_path)
            abs_plan = os.path.abspath(self.plan_file_path)
            if abs_target == abs_plan:
                return True
        except Exception:
            pass
        if os.path.basename(target_path) == os.path.basename(self.plan_file_path):
            return True
        return ".mewcode/plans/" in target_path