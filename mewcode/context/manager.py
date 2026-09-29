"""上下文管理器：负责「对话历史」的体积控制。

LLM 的输入窗口（context_window）是有限的，Agent 跑得越久，历史越长，
总有一天会撑爆窗口。本模块用两种手段给历史"减负"：

- Layer 1：把「超大工具结果」落盘到文件，对话里只留一段简短预览，
          避免一条几十万字符的 ReadFile 输出直接占满窗口。
- Layer 2：当整个对话接近窗口上限时，把早期内容交给 LLM 生成一份「摘要」，
          只保留摘要 + 最近一小段原文，让对话能继续跑下去（auto-compact）。

为入门者：可以把这个文件想象成一个「整理员」——它不断翻看历史，把
过大的、过旧的、过长的内容收缩成更小占位的版本，好让模型始终能装得下。
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from mewcode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
    estimate_tokens,
)
from mewcode.serialization import build_messages

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# 这一大坨数字就是组织"整理员"工作时用的各种阈值。对初学者先抓住三个最关键：
#   - SINGLE / AGGREGATE_CHAR_LIMIT：单条约多少字符就要被落盘（Layer 1 的判定线）
#   - AUTO / MANUAL_COMPACT_SAFETY_MARGIN：离窗口上限留多少"安全垫"就触发摘要（Layer 2）
#   - KEEP_RECENT_* / MIN_KEEP_MESSAGES：压缩时尾部留多少近期原文不摘要
# 其余是配套的“截断/保留”用的细节数字，用到时可回看注释，不必一次全记。

SINGLE_RESULT_CHAR_LIMIT = 50_000
AGGREGATE_CHAR_LIMIT = 200_000
PREVIEW_CHARS = 2_000

KEEP_RECENT_TURNS = 10
OLD_RESULT_SNIP_CHARS = 2_000
SNIPPED_TAG = "<snipped>"

SUMMARY_OUTPUT_RESERVE = 20_000
AUTO_COMPACT_SAFETY_MARGIN = 13_000
MANUAL_COMPACT_SAFETY_MARGIN = 3_000

# Layer 2 "保留近期原文"窗口（对应 Claude Code compact.ts 的
# buildPostCompactMessages messagesToKeep）。压缩时，尾部消息按 token 累计不超过
# KEEP_RECENT_TOKENS、或消息数不少于 MIN_KEEP_MESSAGES（取先满足的条件保底）保留原文，
# 不纳入摘要。累计超过 KEEP_MAX_TOKENS 时停止，防止单条超大消息吞掉整个窗口。
KEEP_RECENT_TOKENS = 10_000
MIN_KEEP_MESSAGES = 5
KEEP_MAX_TOKENS = 40_000

# 前缀 token 数低于此阈值时不值得做摘要——摘要往返的开销比回收的空间还大，
# 退化为不压缩、保留原始历史（避免「压了个寂寞」）。
MIN_SUMMARIZE_PREFIX_TOKENS = 2_000

PERSISTED_TAG = "<persisted-output>"

SESSION_SUBDIR = ".mewcode/session/tool-results"


# ---------------------------------------------------------------------------
# 事件
# ---------------------------------------------------------------------------


@dataclass
class CompactBoundary:
    """
    Layer 2 压缩的结构化结果，上交给 session 层处理。

    `summary` 是大模型对被摘要前缀生成的摘要；`keep` 是 auto_compact 原样保留、
    未做改动的近期尾部消息。session 层（持有 sessionId / 文件句柄）会把二者一起
    内联进一条 compact_boundary 记录，这样 resume 时就能重建压缩后的状态。
    用这种方式把写操作解耦出去，能让 auto_compact 保持纯粹、不依赖任何 session。
    """

    summary: str
    keep: list[Message]


@dataclass
class CompactEvent:
    before_tokens: int
    # 摘要成功时填充，调用方可据此持久化 compact_boundary 记录。
    # 未产出摘要时为 None。
    boundary: CompactBoundary | None = None


# ---------------------------------------------------------------------------
# 内容替换状态 — Design B（决策冻结，不做原地修改）
# ---------------------------------------------------------------------------

@dataclass
class ContentReplacementState:
    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)


@dataclass
class ContentReplacementRecord:
    tool_use_id: str
    replacement: str
    kind: str = "tool-result"


def create_replacement_state() -> ContentReplacementState:
    return ContentReplacementState()


def clone_replacement_state(src: ContentReplacementState) -> ContentReplacementState:
    return ContentReplacementState(
        seen_ids=set(src.seen_ids),
        replacements=dict(src.replacements),
    )


REPLACEMENT_RECORDS_FILENAME = "replacement_records.jsonl"


def append_replacement_records(
    session_dir: Path, records: list[ContentReplacementRecord]
) -> None:
    if not records:
        return
    path = session_dir / REPLACEMENT_RECORDS_FILENAME
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps({
                "kind": r.kind,
                "tool_use_id": r.tool_use_id,
                "replacement": r.replacement,
            }, ensure_ascii=False) + "\n")


def load_replacement_records(session_dir: Path) -> list[ContentReplacementRecord]:
    path = session_dir / REPLACEMENT_RECORDS_FILENAME
    if not path.exists():
        return []
    out: list[ContentReplacementRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            out.append(ContentReplacementRecord(
                kind=obj.get("kind", "tool-result"),
                tool_use_id=obj["tool_use_id"],
                replacement=obj["replacement"],
            ))
    return out


def reconstruct_replacement_state(
    messages: list[Message],
    records: list[ContentReplacementRecord],
    inherited_replacements: Mapping[str, str] | None = None,
) -> ContentReplacementState:
    state = create_replacement_state()
    candidate_ids: set[str] = set()
    for msg in messages:
        for tr in msg.tool_results:
            candidate_ids.add(tr.tool_use_id)
    state.seen_ids.update(candidate_ids)
    for r in records:
        if r.kind == "tool-result" and r.tool_use_id in candidate_ids:
            state.replacements[r.tool_use_id] = r.replacement
    if inherited_replacements:
        for tool_use_id, replacement in inherited_replacements.items():
            if tool_use_id in candidate_ids and tool_use_id not in state.replacements:
                state.replacements[tool_use_id] = replacement
    return state


# ---------------------------------------------------------------------------
# Session 目录管理
# ---------------------------------------------------------------------------

def ensure_session_dir(work_dir: str) -> Path:
    session_dir = Path(work_dir) / SESSION_SUBDIR
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def cleanup_tool_results(session_dir: Path) -> None:
    if session_dir.exists():
        shutil.rmtree(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Layer 1：大型工具结果落盘
# ---------------------------------------------------------------------------
# Layer 1 的思路：如果某次工具结果太大，就别整段塞进对话，而是写成一个文件，
# 对话里只留一条"预览 + 文件路径"占位。下面两个函数一个负责"写文件"，
# 一个负责"生成占位预览文本"。

def persist_tool_result(tool_use_id: str, content: str, session_dir: Path) -> Path:
    """把一条大结果写到磁盘，返回写成的文件路径。

    用 O_EXCL 确保"只写一次"：若该文件已存在（说明本次压缩已处理过），
    捕获 FileExistsError 静默跳过，避免重复写覆盖。
    """
    file_path = session_dir / f"{tool_use_id}.txt"
    try:
        fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        pass
    return file_path


def make_persisted_preview(content: str, file_path: Path) -> str:
    """生成一段人类可读的占位文本：说明内容多大、存到了哪、截取开头预览。"""
    size_kb = len(content.encode("utf-8")) // 1024
    preview = content[:PREVIEW_CHARS]
    return (
        f"{PERSISTED_TAG}\n"
        f"输出太大（{size_kb}KB），完整内容已保存到：\n"
        f"{file_path}\n"
        f"\n"
        f"预览（前 2KB）：\n"
        f"{preview}\n"
        f"</persisted-output>"
    )


def _count_turns(messages: list[Message]) -> int:
    count = 0
    for m in messages:
        if m.role == "assistant" and not m.tool_uses:
            count += 1
    return count


def _copy_message_with_results(
    msg: Message, new_tool_results: list[ToolResultBlock]
) -> Message:
    return Message(
        role=msg.role,
        content=msg.content,
        tool_uses=list(msg.tool_uses),
        tool_results=new_tool_results,
        thinking_blocks=list(msg.thinking_blocks),
    )


def _snip_stale_messages(
    history: list[Message],
) -> list[Message]:
    """Pass 3：把"太久远"的旧工具结果裁剪成占位符。

    只保留最近 KEEP_RECENT_TURNS 轮的原文；更早且内容过长的工具结果，
    统一替换成一句"已裁剪 + 预览"的短占位，进一步减小体积。
    """
    total_turns = _count_turns(history)
    if total_turns <= KEEP_RECENT_TURNS:
        return history

    out: list[Message] = []
    turns_seen = 0
    old_boundary = total_turns - KEEP_RECENT_TURNS

    for msg in history:
        if msg.role == "assistant" and not msg.tool_uses:
            turns_seen += 1
        if turns_seen > old_boundary or not msg.tool_results:
            out.append(msg)
            continue

        new_results: list[ToolResultBlock] = []
        changed = False
        for tr in msg.tool_results:
            if (
                tr.content.startswith(SNIPPED_TAG)
                or tr.content.startswith(PERSISTED_TAG)
                or len(tr.content) <= OLD_RESULT_SNIP_CHARS
            ):
                new_results.append(tr)
                continue
            preview = tr.content[:200]
            orig_len = len(tr.content)
            new_content = (
                f"{SNIPPED_TAG}\n"
                f"(旧结果已裁剪，原始长度 {orig_len} 字符)\n"
                f"{preview}\n"
                f"… (snipped)"
            )
            new_results.append(ToolResultBlock(
                tool_use_id=tr.tool_use_id,
                content=new_content,
                is_error=tr.is_error,
            ))
            changed = True

        out.append(_copy_message_with_results(msg, new_results) if changed else msg)

    return out


def apply_tool_result_budget(
    conversation: ConversationManager,
    session_dir: Path,
    state: ContentReplacementState,
) -> tuple[ConversationManager, list[ContentReplacementRecord]]:
    """给整轮对话的「工具结果」做体积预算控制（本文件最核心的函数）。

    【设计原则：Design B——不改原对象，而是返回一个全新的副本】
    Python 里可变对象（如 ConversationManager）传入函数后，如果在原对象上直接做
    `.history = xxx` 这类修改，会改动到**调用方**持有同一个对象的数据，副作用容易
    藏得很深。这里的设计是"读完→构造新的→返回新的"，原 conversation 原封不动，
    更安全也更容易被测试。代价是：需要在函数末尾把旧对象的一系列属性逐个搬到
    新对象上（见注释标注的属性搬运段）。

    【这个函数在做什么（给 Agent 初学者的直观理解）】
    它像一位"预算管家"，逐条检查对话里每条工具结果（tool_result）占了多少字符，
    并分三趟（Pass）处理：
      - Pass 1：某一条结果 *单条* 字数超限 → 落盘成文件，对话里换成一段简短预览。
      - Pass 2：把本消息里若干条结果 *加起来的* 字数超限 → 挑最大的几条同样落盘。
      - Pass 3：对太早发生（已超过保留轮数）的旧结果 → 裁剪成一句短占位。
    这样窗口里永远不塞几十万字符的大块原文。

    【关于返回值与 state 的"进/出"约定（易混淆点）】
    - 返回值 `new_records`：本轮新做出的"替换决策"清单，调用方会拿去持久化（写文件），
      这样会话恢复（resume）时还能还原出压缩效果。
    - 参数 `state`：会被就地修改（mutate）！函数里把已识别的 id 塞进 `seen_ids`、
      把已做替换的记录写进 `replacements`。初学者注意区分——返回的元组是"新的干净数据"，
      而 `state` 是"被累积更新的账本"，两者用途不同。

    一句话总结：**进来一沓消息，出去一份"瘦身版副本"+ 一份"替换记录"**。
    """
    new_records: list[ContentReplacementRecord] = []
    new_history: list[Message] = []

    # 遍历对话里每一条消息。注意 `history` 是消息列表，每条消息可携带若干 tool_results。
    for msg in conversation.history:
        # 这条消息根本没有工具结果，无需处理，原样搬进新列表即可。
        if not msg.tool_results:
            new_history.append(msg)
            continue

        # decisions：本消息里"每个 tool_use_id → 最终要写入对话的内容"（原文或预览）。
        # fresh：本轮**首次见到**、还没有任何既定决策、需要现场判断的工具结果。
        decisions: dict[str, str] = {}
        fresh: list[ToolResultBlock] = []

        for tr in msg.tool_results:
            # 情形一：这个结果之前已经做过替换决策（在 state.replacements 里有记录）。
            # 直接沿用之前定下的替换内容，保证跨 session 决策一致。
            if tr.tool_use_id in state.replacements:
                decisions[tr.tool_use_id] = state.replacements[tr.tool_use_id]
            # 情形二：之前见过它，但当时决定"不替换、保留原文"。同样沿用原文。
            elif tr.tool_use_id in state.seen_ids:
                decisions[tr.tool_use_id] = tr.content
            # 情形三：内容本身已经带了 <persisted-output> 标签（可能是工具自己打的，
            # 说明它已经被落盘过了）。把它当作一个"已定案决策"记录下来，避免重复处理。
            elif tr.content.startswith(PERSISTED_TAG):
                state.seen_ids.add(tr.tool_use_id)
                state.replacements[tr.tool_use_id] = tr.content
                decisions[tr.tool_use_id] = tr.content
                new_records.append(ContentReplacementRecord(
                    tool_use_id=tr.tool_use_id, replacement=tr.content,
                ))
            # 情形四：全新的结果。先放进 fresh，交给下面的 Pass 1 / Pass 2 处理。
            else:
                fresh.append(tr)

        # ---- Pass 1：单条超限 ------------------------------------------------
        # 语法说明：`set` 是无序不重复的容器，和 `list` 很像但元素不会重复。
        # persisted_p1 记录本轮已被 Pass 1 落盘的那些 id，好让 Pass 2 跳过它们——一条
        # 结果只要落盘成文件了，就不该再被"聚合超限"逻辑二次落盘。
        persisted_p1: set[str] = set()
        for tr in fresh:
            # len(tr.content) 是字符串的字符数（注意：不是 token 数，只是粗略衡量体积）。
            if len(tr.content) > SINGLE_RESULT_CHAR_LIMIT:
                # 把原文写到磁盘文件，得到文件路径 fp。
                fp = persist_tool_result(tr.tool_use_id, tr.content, session_dir)
                # 生成一段人类可读的"预览占位文本"：说明多大、存在哪、给前 2KB 预览。
                preview = make_persisted_preview(tr.content, fp)
                # 把"用预览替换原文"这条决策记录下来。
                decisions[tr.tool_use_id] = preview
                state.replacements[tr.tool_use_id] = preview
                state.seen_ids.add(tr.tool_use_id)
                new_records.append(ContentReplacementRecord(
                    tool_use_id=tr.tool_use_id, replacement=preview,
                ))
                persisted_p1.add(tr.tool_use_id)

        # ---- Pass 2：聚合超限 ------------------------------------------------
        # remaining = 还没被 Pass 1 落盘的全部 fresh 结果。
        # 列表推导式（list comprehension）是 Python 极常用的写法：
        #   [表达式 for 变量 in 列表 if 条件]  →  得到新列表。
        # 这里等价于下面的循环：
        #   remaining = []
        #   for tr in fresh:
        #       if tr.tool_use_id not in persisted_p1:
        #           remaining.append(tr)
        remaining = [tr for tr in fresh if tr.tool_use_id not in persisted_p1]

        # `sum(...)` 把一堆数字相加。这里计算"这条消息最终要带进对话的总量" =
        # 已有决策的长度（decisions.values() 是"预览或原文"，逐个取 len）+ 仍未处理
        # 的剩余结果长度。
        total = sum(len(c) for c in decisions.values()) + sum(
            len(tr.content) for tr in remaining
        )

        # AGGREGATE_CHAR_LIMIT 是"单条消息允许的总量上限"。
        if total > AGGREGATE_CHAR_LIMIT:
            # sorted(..., key=..., reverse=True) 按结果长度降序排列：先处理"最大的那条"。
            # key=lambda tr: len(tr.content) 意为"用每条结果的长度作为排序依据"。
            # lambda 就是一句话定义的小函数，这里等价于写 def g(tr): return len(tr.content)。
            ranked = sorted(remaining, key=lambda tr: len(tr.content), reverse=True)
            for tr in ranked:
                # 只要总量回到上限内，就停止压缩，剩下的不处理。
                if total <= AGGREGATE_CHAR_LIMIT:
                    break
                fp = persist_tool_result(tr.tool_use_id, tr.content, session_dir)
                preview = make_persisted_preview(tr.content, fp)
                old_len = len(tr.content)  # 记下替换前的字符数，以便下面更新预算。
                decisions[tr.tool_use_id] = preview
                state.replacements[tr.tool_use_id] = preview
                state.seen_ids.add(tr.tool_use_id)
                new_records.append(ContentReplacementRecord(
                    tool_use_id=tr.tool_use_id, replacement=preview,
                ))
                # 更新 budget：把"原文长度"换成"预览长度"，差额即本次回收的空间。
                total -= old_len - len(preview)

        # ---- 收尾：登记"已见但未替换"的结果 ---------------------------------
        # 走到这里的 fresh 不超限也不需落盘，走原样。仍要用 seen_ids 登记 id，
        # 这样下次处理时走"情形二"分支，不会再进 fresh。seen_ids 的意义：记住"这个
        # 结果我们已经见过了、咱们处理过了"，避免每次运行都重新判定一遍。
        for tr in fresh:
            if tr.tool_use_id not in state.replacements:
                state.seen_ids.add(tr.tool_use_id)
                decisions[tr.tool_use_id] = tr.content

        # 按**原始顺序**重建工具结果列表。顺序很重要：模型依赖 tool_use → tool_result
        # 的配对顺序，不能打乱。这里再做一次列表推导式，把 decisions 中定好的内容
        # 填回新的 ToolResultBlock，is_error 保持原样。
        new_tool_results = [
            ToolResultBlock(
                tool_use_id=tr.tool_use_id,
                content=decisions[tr.tool_use_id],
                is_error=tr.is_error,
            )
            for tr in msg.tool_results
        ]
        # _copy_message_with_results 构造一条"新"消息：role/content/tool_uses/thinking 原样，
        # 只替换掉 tool_results。这样就是一条全新的 Message，不会改动原消息对象。
        new_history.append(_copy_message_with_results(msg, new_tool_results))

    # ---- Pass 3：在新 history 上裁剪过期的旧结果（无状态） ------------------
    # 所谓"无状态（stateless）"：这个函数只依赖传入的列表，不读也不改任何外部状态，
    # 同样的入参永远得到同样的结果，更容易调试。边界漂移（裁剪边界的轻微出入）是
    # 已接受的设计取舍，不影响整体正确性。
    new_history = _snip_stale_messages(new_history)

    # ---- 属性搬运：把旧 conversation 的状态搬到新对象 ------------------------
    # 注意：这里**不是**深拷贝，而是手动挑着复制关键属性。因为原对象没被动过，
    # 新对象必须把它没有处理过的信息（是否已注入系统提示、token 锚点等）一并带上，
    # 否则重建出的对话会"失忆"。初学者可以把它理解成"复制一份申请单，把没改的那几栏
    # 原样抄过来"。
    new_conv = ConversationManager()
    new_conv.history = new_history
    new_conv.env_injected = conversation.env_injected
    new_conv.ltm_injected = conversation.ltm_injected
    new_conv.last_input_tokens = conversation.last_input_tokens
    new_conv.baseline_tokens = conversation.baseline_tokens
    new_conv.anchor_count = conversation.anchor_count

    return new_conv, new_records


# ---------------------------------------------------------------------------
# Layer 2：全对话摘要（Auto-Compact）
# ---------------------------------------------------------------------------
# Layer 2 的思路：当历史整体太大模型装不下时，把"前半段"交给 LLM 压成一份
# 结构化摘要（SUMMARY_PROMPT 规定摘要必须包含哪些章节），后半段的近期原文
# 原样保留。这样对话体积骤减，同时模型仍保有近期细节与早期脉络的概述。

def compute_compact_threshold(context_window: int, manual: bool = False) -> int:
    """算出"安全触发线"：窗口上限减去输出预留和安全垫，达到这条线就该压缩。"""
    effective = context_window - SUMMARY_OUTPUT_RESERVE
    margin = MANUAL_COMPACT_SAFETY_MARGIN if manual else AUTO_COMPACT_SAFETY_MARGIN
    return effective - margin


def should_auto_compact(last_input_tokens: int, context_window: int) -> bool:
    return last_input_tokens >= compute_compact_threshold(context_window)


SUMMARY_PROMPT = """\
你是一个对话摘要助手。你只能输出纯文本，不能调用任何工具。

请对下面的对话生成一份结构化摘要。

先在 <analysis> 标签中梳理对话中发生了什么（这部分会被丢弃），然后在 <summary> 标签中输出正式摘要。

<summary> 必须包含以下 9 个部分：

1. **主要请求和意图**：用户到底想做什么
2. **关键技术概念**：讨论过的重要技术点
3. **文件和代码段**：涉及哪些文件，关键代码片段要保留
4. **错误和修复**：遇到了什么错，怎么解决的
5. **问题解决过程**：解决问题的思路和方法
6. **所有用户消息**：用户说过的所有非工具结果的话（原文保留，不可改写！）
7. **待办任务**：还没完成的事
8. **当前工作**：最近在做什么（要最详细）
9. **可能的下一步**：接下来打算做什么

提醒：不要调用任何工具。工具调用会被拒绝，你会失败。只输出纯文本。"""


def extract_summary(llm_output: str) -> str:
    start = llm_output.find("<summary>")
    end = llm_output.find("</summary>")
    if start == -1 or end == -1:
        return llm_output
    return llm_output[start + len("<summary>"):end].strip()


def build_compact_messages(
    summary: str,
    attachment: str = "",
    has_keep_tail: bool = False,
    transcript_path: str = "",
) -> list[Message]:
    content = "本次会话延续自之前的对话，因上下文空间不足进行了压缩。以下是早期对话的摘要：\n\n" + summary
    if has_keep_tail:
        content += "\n\n近期消息已原样保留。"
    if transcript_path:
        content += f"\n\n如果你需要压缩前的具体细节（代码片段、报错信息等），请用 ReadFile 读取完整会话记录：{transcript_path}"
    if attachment:
        content += "\n\n---\n\n" + attachment
    return [
        Message(role="user", content=content),
    ]


# ---------------------------------------------------------------------------
# 压缩后恢复状态
# ---------------------------------------------------------------------------

# 追加到摘要 user 消息的恢复附件限制。compact 会清空工作对话；
# 没有这些快照，模型会忘记刚读过哪些文件、正在执行哪个 skill 的 SOP。
RECOVERY_FILE_LIMIT = 5
RECOVERY_TOKENS_PER_FILE = 5_000
RECOVERY_SKILLS_BUDGET = 25_000
RECOVERY_TOKENS_PER_SKILL = 5_000
_RECOVERY_CHARS_PER_TOKEN = 3.5


@dataclass
class FileReadRecord:
    path: str
    content: str
    timestamp: float


@dataclass
class SkillInvocationRecord:
    name: str
    body: str
    timestamp: float


class RecoveryState:
    """能在 Layer 2 压缩中存活下来的 per-agent 快照。

    记录 ReadFile 返回的字节内容，以及各个 skill 被调用时附带的 SOP 正文。
    这些记录会被重新附加到摘要的 user 消息上，这样即便对话记录被压缩清空，
    模型仍然保有可用的工作上下文。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileReadRecord] = {}
        self._skills: dict[str, SkillInvocationRecord] = {}

    def record_file_read(self, path: str, content: str) -> None:
        if not path:
            return
        with self._lock:
            self._files[path] = FileReadRecord(
                path=path, content=content, timestamp=time.time()
            )

    def record_skill_invocation(self, name: str, body: str) -> None:
        if not name:
            return
        with self._lock:
            self._skills[name] = SkillInvocationRecord(
                name=name, body=body, timestamp=time.time()
            )

    def snapshot_files(self, limit: int) -> list[FileReadRecord]:
        with self._lock:
            records = list(self._files.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if limit > 0:
            records = records[:limit]
        return records

    def snapshot_skills(self) -> list[SkillInvocationRecord]:
        with self._lock:
            records = list(self._skills.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records


def _approx_tokens(s: str) -> int:
    if not s:
        return 0
    return int(len(s) / _RECOVERY_CHARS_PER_TOKEN)


def _truncate_by_tokens(s: str, token_budget: int) -> str:
    if token_budget <= 0 or not s:
        return s
    if _approx_tokens(s) <= token_budget:
        return s
    max_chars = int(token_budget * _RECOVERY_CHARS_PER_TOKEN)
    if max_chars <= 0 or max_chars >= len(s):
        return s
    return s[:max_chars] + "\n… (内容已截断)"


def _first_line(s: str) -> str:
    for line in s.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_recovery_attachment(
    state: RecoveryState | None,
    tool_schemas: list[Mapping[str, Any]] | None,
) -> str:
    """渲染压缩后附件的四个小节。

    没有任何值得附加的内容时返回 ""，让调用方保持摘要消息干净。
    `tool_schemas` 应当是 agent 在下一次请求中将要发送的 schema —— 这里用其中的
    名称和描述来提醒模型当前都接入了哪些工具。
    """
    sections: list[str] = []

    if state is not None:
        files = state.snapshot_files(RECOVERY_FILE_LIMIT)
        if files:
            buf = ["## 最近读过的文件\n",
                   "以下快照是文件读取工具上次返回的内容。如需当前字节请重新读取。\n"]
            for rec in files:
                content = _truncate_by_tokens(rec.content, RECOVERY_TOKENS_PER_FILE)
                ts = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(rec.timestamp)
                )
                buf.append(f"### {rec.path}  (read {ts})\n")
                buf.append("```\n")
                buf.append(content)
                if not content.endswith("\n"):
                    buf.append("\n")
                buf.append("```\n")
            sections.append("".join(buf))

        skills = state.snapshot_skills()
        if skills:
            buf = ["## 已激活的技能\n",
                   "下列技能在本会话中被调用过，其触发条件仍然适用。\n"]
            used = 0
            emitted = False
            for sk in skills:
                body = _truncate_by_tokens(sk.body, RECOVERY_TOKENS_PER_SKILL)
                tokens = _approx_tokens(body) + _approx_tokens(sk.name) + 8
                if used + tokens > RECOVERY_SKILLS_BUDGET:
                    break
                used += tokens
                buf.append(f"### {sk.name}\n\n{body}\n")
                emitted = True
            if emitted:
                sections.append("".join(buf))

    if tool_schemas:
        buf = ["## 可用工具\n",
               "你仍然可以调用以下工具，需要时直接发起调用即可：\n"]
        for t in tool_schemas:
            name = t.get("name") if isinstance(t, Mapping) else None
            if not name:
                continue
            desc = t.get("description", "") if isinstance(t, Mapping) else ""
            desc = _first_line(desc or "")
            if desc:
                buf.append(f"- {name} — {desc}\n")
            else:
                buf.append(f"- {name}\n")
        sections.append("".join(buf))

    if not sections:
        return ""

    sections.append(
        "## 提示\n\n以上恢复的上下文是重建的。若需要原文代码、错误信息或用户原话，"
        "请用文件读取工具重新读取，不要根据摘要猜测细节。\n"
    )
    return "\n".join(sections)


def _group_messages_by_turn(messages: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    current: list[Message] = []
    for msg in messages:
        current.append(msg)
        if msg.role == "assistant" and not msg.tool_uses:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _message_tokens(msg: Message) -> int:
    """估算单条消息的 token 数，复用共享的字符数启发式算法。"""
    return estimate_tokens([msg])


def _compute_keep_start_index(messages: list[Message]) -> int:
    """决定压缩时尾部要原样保留多少条消息。

    从尾部向头部遍历 `messages`，逐条累加 token 估算值。只要还有任一保底条件
    未满足——累计 token 尚未达到 KEEP_RECENT_TOKENS，或保留的消息数仍少于
    MIN_KEEP_MESSAGES——当前消息就会被纳入保留窗口；但一旦纳入下一条消息会使
    保留总量超过 KEEP_MAX_TOKENS，遍历立即停止（这样单条超大的尾部消息就不会把
    整个 history 都拖进窗口）。

    返回第一条被保留消息的下标（keepStartIndex）。原始遍历结束后，必要时会把这个
    下标往前挪，确保被保留的 tool_result 不会和它对应的 tool_use 被拆散——
    参见 `_align_keep_start_to_tool_pair`。
    """
    n = len(messages)
    if n == 0:
        return 0

    kept_tokens = 0
    kept_count = 0
    keep_start = n  # 尚未保留任何消息

    for i in range(n - 1, -1, -1):
        tok = _message_tokens(messages[i])

        # 在已经保留了至少一条消息的前提下，如果纳入当前消息会突破硬上限则停止
        # （但绝不拒绝保留最后一条消息，即使它单独就超限）。
        if kept_count > 0 and kept_tokens + tok > KEEP_MAX_TOKENS:
            break

        kept_tokens += tok
        kept_count += 1
        keep_start = i

        # 保底条件已满足（token 下限或消息条数下限达到其一）：
        # 近期原文保留足够了，停止回溯。
        if kept_tokens >= KEEP_RECENT_TOKENS or kept_count >= MIN_KEEP_MESSAGES:
            break

    return _align_keep_start_to_tool_pair(messages, keep_start)


def _align_keep_start_to_tool_pair(messages: list[Message], keep_start: int) -> int:
    """把 keep_start 往前挪，确保我们绝不会保留一个孤立的 tool_result。

    携带 tool_results 的 user 消息，会和它前面那条发起对应 tool_uses 的 assistant
    消息配成一对。如果 keep_start 正好落在这样一条 user 消息上，就把它往前回退到
    （至少）配对的那条 assistant 消息，让 tool_use 与 tool_result 的配对关系保持完整。
    宁可多保留一对，也不要只保留半对（一个模型无法归属到任何调用的悬空 tool_result）。
    """
    while 0 < keep_start < len(messages):
        msg = messages[keep_start]
        if msg.role == "user" and msg.tool_results:
            prev = messages[keep_start - 1]
            if prev.role == "assistant" and prev.tool_uses:
                keep_start -= 1
                continue
        break
    return keep_start


def _prefix_too_small_to_compact(prefix: list[Message]) -> bool:
    """当摘要 `prefix` 能回收的空间太少、不值得做时返回 True。"""
    if not prefix:
        return True
    return estimate_tokens(prefix) < MIN_SUMMARIZE_PREFIX_TOKENS


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


@dataclass
class CompactCircuitBreaker:
    max_failures: int = 3
    consecutive_failures: int = field(default=0, init=False)

    def record_failure(self) -> None:
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0


    def is_open(self) -> bool:
        return self.consecutive_failures >= self.max_failures


# ---------------------------------------------------------------------------
# Auto-compact 编排器
# ---------------------------------------------------------------------------

async def auto_compact(
    conversation: ConversationManager,
    client: Any,
    context_window: int,
    session_dir: Path,
    protocol: str = "anthropic",
    manual: bool = False,
    breaker: CompactCircuitBreaker | None = None,
    recovery: RecoveryState | None = None,
    tool_schemas: list[Mapping[str, Any]] | None = None,
    transcript_path: str = "",
) -> CompactEvent | str | None:
    """Layer 2 的编排入口：看情况决定并执行一次历史压缩。

    整体流程可浓缩为"判断 → 摘要 → 重建"：
      1. 判断是否该压缩（手动强制，或 token 已超过安全线），并检查熔断器；
      2. 若有必要，把"待摘要前缀"交给 LLM 生成结构化摘要（失败自动降载重试）；
      3. 重建对话 = 摘要消息 + 尾部原文，替换原历史并清空用量锚点。

    返回值三选一：发生了压缩则返回 CompactEvent；判断没必要则返回 None；
    过程出错则返回错误说明字符串（str）。
    """
    threshold = compute_compact_threshold(context_window, manual=manual)

    # 以真实 API 用量为锚点做阈值判断：current_tokens() 返回上次计费基准
    # （input + cache_read + cache_creation + output）加上锚点之后新增消息的
    # 字符估算。冷启动或刚压缩清空锚点时，退化为对整个 history 做字符估算。
    current = conversation.current_tokens()

    if not manual and current < threshold:
        return None

    if not manual and breaker is not None and breaker.is_open():
        return "自动压缩已熔断（连续失败 3 次），请手动处理或使用 /compact"

    before_tokens = current

    # 决定保留多少尾部消息原文。只有前缀 messages[:keep_start] 会被摘要；
    # messages[keep_start:] 原样保留，让模型看到近期原文而非靠有损摘要复述。
    keep_start = _compute_keep_start_index(conversation.history)
    to_summarize = conversation.history[:keep_start]
    keep_tail = conversation.history[keep_start:]

    # 待摘要的前缀太小时退化为不压缩——要么全部消息都落在保留窗口内
    # （keep_start <= 0），要么摘要回收的 token 还不够摘要本身的开销。
    if keep_start <= 0 or _prefix_too_small_to_compact(to_summarize):
        return None

    messages_for_summary = build_messages(list(to_summarize), protocol)

    summary_messages: list[dict[str, Any]] = [
        {"role": "user", "content": SUMMARY_PROMPT},
    ]
    summary_messages.extend(messages_for_summary)
    summary_messages.append(
        {"role": "user", "content": "请根据以上对话生成结构化摘要。记住：不要调用任何工具。"}
    )

    summary_conv = ConversationManager()
    summary_conv.history = [
        Message(role="user", content=SUMMARY_PROMPT),
    ]
    # 只摘要前缀；保留的尾部在下面重建时原样拼回。
    for msg in to_summarize:
        summary_conv.history.append(msg)
    summary_conv.history.append(
        Message(role="user", content="请根据以上对话生成结构化摘要。记住：不要调用任何工具。")
    )

    max_retries = 3
    llm_output: str | None = None

    for attempt in range(max_retries):
        try:
            from mewcode.tools.base import StreamEnd, StreamEvent, TextDelta

            collected_text = ""
            async for event in client.stream(summary_conv, system=SUMMARY_PROMPT):
                if isinstance(event, TextDelta):
                    collected_text += event.text
                elif isinstance(event, StreamEnd):
                    pass
            llm_output = collected_text
            break

        except Exception as e:
            err_msg = str(e).lower()
            if "prompt" in err_msg and "long" in err_msg or "too many" in err_msg:
                groups = _group_messages_by_turn(summary_conv.history[1:-1])
                drop_count = max(1, len(groups) // 5)
                remaining = groups[drop_count:]
                summary_conv.history = (
                    [summary_conv.history[0]]
                    + [m for g in remaining for m in g]
                    + [summary_conv.history[-1]]
                )
                continue
            if breaker is not None:
                breaker.record_failure()
            return f"摘要生成失败: {e}"

    if llm_output is None:
        if breaker is not None:
            breaker.record_failure()
        return "摘要生成失败：多次重试后仍超出上下文限制"

    summary = extract_summary(llm_output)
    attachment = build_recovery_attachment(recovery, tool_schemas)
    # 重建 = 摘要(user) + 尾部原文。
    new_messages = build_compact_messages(
        summary,
        attachment=attachment,
        has_keep_tail=bool(keep_tail),
        transcript_path=transcript_path,
    )
    new_messages = new_messages + list(keep_tail)

    # replace_history 替换为重建后的对话并将用量锚点清零
    # （baseline_tokens / anchor_count / last_input_tokens），这是必须的：
    # 旧的 anchor_count 对应压缩前的消息列表，现在已无意义，
    # 不清零会导致 current_tokens() 对增量的估算出错。
    # 下一次 API 响应会基于重建后的 history 重新锚定。
    conversation.replace_history(new_messages)
    cleanup_tool_results(session_dir)

    if breaker is not None:
        breaker.record_success()

    # 将结构化的 boundary（摘要 + 保留的尾部原文）交给 session 层，
    # 由它持久化为一条 compact_boundary 记录。keep tail 就是拼回重建 history 的那段。
    return CompactEvent(
        before_tokens=before_tokens,
        boundary=CompactBoundary(summary=summary, keep=list(keep_tail)),
    )
