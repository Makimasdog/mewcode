"""
progress.py — 进度追踪（团队成员的实时状态面板）
=============================================================

【这个模块做什么】
提供 TeammateProgress 类，追踪每个团队成员的实时工作状态：
- 正在使用什么工具
- 消耗了多少 Token
- 当前的工作描述（用于 UI 旋转加载动画）

【趣味设计：Spinner Verbs】
进度面板会显示一个有趣的英文动词来描述成员正在做什么：
"Accomplishing"、"Baking"、"Cogitating"、"Mewing"、"Noodling"...
这些动词让等待过程不那么枯燥。

【线程安全】
TeammateProgress 可能被多个线程同时更新（Agent 执行线程 + UI 刷新线程），
所以所有写操作都用 threading.Lock 保护。

【对外接口】
- ToolActivity        工具活动描述
- TeammateProgress    成员进度追踪器
- random_verb()       获取随机趣味动词
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


# 趣味动词列表：UI 旋转加载动画显示的「正在 XX...」
# 从 "Accomplishing" 到 "Zigzagging"，让等待不再无聊
SPINNER_VERBS = [
    "Accomplishing", "Architecting", "Baking", "Beboppin'", "Befuddling",
    "Bloviating", "Boogieing", "Boondoggling", "Bootstrapping", "Brewing",
    "Calculating", "Canoodling", "Caramelizing", "Cascading", "Cerebrating",
    "Choreographing", "Churning", "Coalescing", "Cogitating", "Combobulating",
    "Composing", "Computing", "Concocting", "Considering", "Contemplating",
    "Cooking", "Crafting", "Creating", "Crunching", "Crystallizing",
    "Cultivating", "Deciphering", "Deliberating", "Dilly-dallying",
    "Discombobulating", "Doodling", "Elucidating", "Enchanting", "Envisioning",
    "Fermenting", "Finagling", "Flambéing", "Flibbertigibbeting", "Flummoxing",
    "Forging", "Frolicking", "Gallivanting", "Garnishing", "Generating",
    "Germinating", "Grooving", "Harmonizing", "Hatching", "Honking",
    "Hullaballooing", "Ideating", "Imagining", "Improvising", "Incubating",
    "Inferring", "Infusing", "Kneading", "Lollygagging", "Manifesting",
    "Marinating", "Meandering", "Metamorphosing", "Mewing", "Moonwalking",
    "Moseying", "Mulling", "Musing", "Noodling", "Orbiting", "Orchestrating",
    "Percolating", "Philosophising", "Pondering", "Pontificating", "Pouncing",
    "Purring", "Puzzling", "Razzle-dazzling", "Ruminating", "Scampering",
    "Simmering", "Sketching", "Spelunking", "Spinning", "Sprouting",
    "Synthesizing", "Thinking", "Tinkering", "Transfiguring", "Transmuting",
    "Undulating", "Unfurling", "Unravelling", "Vibing", "Wandering",
    "Whisking", "Working", "Wrangling", "Zigzagging",
]


def random_verb() -> str:
    """获取一个随机趣味动词（用于进度面板的加载动画）"""
    return random.choice(SPINNER_VERBS)


@dataclass
class ToolActivity:
    """
    工具活动记录。

    描述一次工具调用的摘要信息：
    - tool_name:    工具名称（如 "ReadFile"、"Bash"）
    - description:  人类可读的描述（如 "Reading src/main.py"）
    """
    tool_name: str
    description: str

    @classmethod
    def from_tool_use(cls, tool_name: str, args: dict) -> ToolActivity:
        """从工具调用参数创建活动记录（自动生成描述）"""
        desc = _describe(tool_name, args)
        return cls(tool_name=tool_name, description=desc)


def _describe(tool_name: str, args: dict) -> str:
    """
    根据工具名称和参数生成人类可读的描述。

    每种工具有特定的描述格式：
    - ReadFile  → "Reading {file_path}"
    - EditFile  → "Editing {file_path}"
    - WriteFile → "Writing {file_path}"
    - Bash      → "Running {command[:40]}"（命令截断到 40 字符）
    - Glob      → "Searching {pattern}"
    - Grep      → "Grepping {pattern}"
    - 其他      → 直接显示工具名
    """
    match tool_name:
        case "ReadFile":
            return f"Reading {args.get('file_path', '')}"
        case "EditFile":
            return f"Editing {args.get('file_path', '')}"
        case "WriteFile":
            return f"Writing {args.get('file_path', '')}"
        case "Bash":
            cmd = str(args.get("command", ""))
            return f"Running {cmd[:40]}{'…' if len(cmd) > 40 else ''}"
        case "Glob":
            return f"Searching {args.get('pattern', '')}"
        case "Grep":
            return f"Grepping {args.get('pattern', '')}"
        case _:
            return tool_name


@dataclass
class TeammateProgress:
    """
    团队成员实时进度追踪器（线程安全）。

    追踪信息：
    - name:              成员名称
    - team_name:         所属团队名称
    - status:            运行状态（running / completed / stopped / failed）
    - tool_use_count:    工具调用总次数
    - token_count:       当前 Token 消耗量
    - last_activity:     最近一次工具活动
    - recent_activities: 最近 5 次工具活动（滑动窗口）
    - spinner_verb:      趣味动词（UI 加载动画用）
    - start_time:        开始时间（monotonic 时钟，用于计算耗时）
    - last_message:      最新的流式文本输出

    线程安全：
    所有修改操作都通过 _lock 保护，因为 Agent 执行线程和 UI 刷新线程
    可能同时访问这个对象。
    """
    name: str
    team_name: str
    status: str = "running"
    tool_use_count: int = 0
    token_count: int = 0
    last_activity: Optional[ToolActivity] = None
    recent_activities: list[ToolActivity] = field(default_factory=list)
    spinner_verb: str = field(default_factory=random_verb)
    start_time: float = field(default_factory=time.monotonic)
    last_message: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_tool_use(self, tool_name: str, args: dict) -> None:
        """
        记录一次工具调用。

        更新：
        - tool_use_count += 1
        - last_activity = 当前活动
        - recent_activities 追加（保留最近 5 条，滑动窗口）
        """
        with self._lock:
            self.tool_use_count += 1
            act = ToolActivity.from_tool_use(tool_name, args)
            self.last_activity = act
            self.recent_activities.append(act)
            if len(self.recent_activities) > 5:
                self.recent_activities.pop(0)  # 移除最旧的

    def record_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """记录 Token 消耗量（输入 + 输出）"""
        with self._lock:
            self.token_count = input_tokens + output_tokens

    @property
    def activity_summary(self) -> str:
        """
        获取当前活动摘要（用于 UI 显示）。

        如果有工具活动 → 显示最近工具的描述
        否则 → 显示趣味动词（如 "Mewing..."）
        """
        with self._lock:
            if self.last_activity:
                return self.last_activity.description
            return self.spinner_verb

    @staticmethod
    def format_tokens(n: int) -> str:
        """
        格式化 Token 数量（人类可读）。

        规则：
        - >= 1M → "1.2M"
        - >= 1k → "12.3k"
        - < 1k  → "456"
        """
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)
