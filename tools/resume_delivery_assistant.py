#!/usr/bin/env python3
"""校招简历投递助手：JD 分析、简历定向草稿和投递跟踪。

该工具只使用用户提供的事实，不调用网络，也不会自动提交申请。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = {
    "name": "你的姓名",
    "target_roles": ["后端开发", "数据分析"],
    "education": [],
    "skills": ["Python"],
    "projects": [
        {
            "name": "项目名称",
            "summary": "一句话说明项目目标和你的职责。",
            "skills": ["Python"],
            "bullets": ["请替换为真实的项目成果，保留可核验的指标。"],
        }
    ],
    "achievements": [],
}

DEFAULT_STORE = {"applications": []}

# 用于提高中文 JD 的稳定性；未命中的词仍会从用户 profile 中补充。
KNOWN_TERMS = {
    "python", "java", "c++", "javascript", "typescript", "go", "rust", "sql",
    "mysql", "postgresql", "redis", "kafka", "docker", "kubernetes", "linux",
    "git", "http", "tcp", "算法", "数据结构", "机器学习", "深度学习", "自然语言处理",
    "数据分析", "数据挖掘", "后端", "前端", "测试", "产品", "运营", "项目管理",
    "微服务", "分布式", "高并发", "消息队列", "数据库", "云计算", "人工智能",
    "react", "vue", "spring", "fastapi", "django", "pytorch", "tensorflow",
}
STOPWORDS = {
    "负责", "参与", "熟悉", "了解", "具有", "优先", "能够", "以及", "相关", "岗位",
    "要求", "工作", "经验", "能力", "完成", "进行", "使用", "良好", "以上", "以下",
}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"无法读取 JSON 文件 {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())


def extract_terms(text: str, extra_terms: list[str] | None = None) -> list[str]:
    text = normalize(text)
    found: set[str] = set()
    for term in KNOWN_TERMS | {normalize(t) for t in (extra_terms or []) if t}:
        if term and term in text:
            found.add(term)
    # 补充英文技术词，避免只依赖固定词表。
    for token in re.findall(r"[a-z][a-z0-9+#.-]{1,}", text):
        if token not in STOPWORDS and len(token) > 1:
            found.add(token)
    return sorted(found)


def profile_text(profile: dict[str, Any]) -> str:
    chunks = [" ".join(map(str, profile.get("skills", [])))]
    for project in profile.get("projects", []):
        chunks.extend([
            str(project.get("name", "")),
            str(project.get("summary", "")),
            " ".join(map(str, project.get("skills", []))),
            " ".join(map(str, project.get("bullets", []))),
        ])
    chunks.extend(map(str, profile.get("achievements", [])))
    return " ".join(chunks)


@dataclass
class Analysis:
    terms: list[str]
    matched: list[str]
    gaps: list[str]
    score: int
    evidence: dict[str, list[str]]


def analyze(profile: dict[str, Any], jd: str) -> Analysis:
    profile_terms = set(extract_terms(profile_text(profile), profile.get("skills", [])))
    jd_terms = extract_terms(jd, profile.get("skills", []))
    matched = [term for term in jd_terms if term in profile_terms]
    gaps = [term for term in jd_terms if term not in profile_terms]
    score = round(100 * len(matched) / len(jd_terms)) if jd_terms else 0
    evidence: dict[str, list[str]] = {}
    for term in matched:
        items = []
        for project in profile.get("projects", []):
            blob = normalize(" ".join(map(str, [project.get("name", ""), project.get("summary", ""), *project.get("skills", []), *project.get("bullets", [])])))
            if term in blob:
                items.append(str(project.get("name", "未命名项目")))
        if term in normalize(" ".join(map(str, profile.get("skills", [])))):
            items.insert(0, "技能清单")
        evidence[term] = list(dict.fromkeys(items))
    return Analysis(jd_terms, matched, gaps, score, evidence)


def analysis_markdown(profile: dict[str, Any], job_path: Path, result: Analysis) -> str:
    lines = [
        f"# JD 分析：{job_path.stem}", "", f"- 候选人：{profile.get('name', '未填写')}",
        f"- 关键词覆盖率：**{result.score}%**（{len(result.matched)}/{len(result.terms)}）", "",
        "## 已匹配关键词", "",
    ]
    lines.append("、".join(result.matched) if result.matched else "暂无")
    lines += ["", "## 待补证据或需确认的关键词", ""]
    lines.append("、".join(result.gaps) if result.gaps else "暂无")
    lines += ["", "## 证据映射", "", "| 关键词 | 事实来源 |", "|---|---|"]
    for term in result.matched:
        lines.append(f"| {term} | {'、'.join(result.evidence.get(term) or ['未定位到项目'])} |")
    lines += ["", "## 使用建议", "", "- 只补充你能举证的关键词；当前缺口不能直接写进简历。",
              "- 优先调整项目顺序和 bullet 顺序，不改写事实和指标。", ""]
    return "\n".join(lines)


def tailored_resume(profile: dict[str, Any], result: Analysis, jd_path: Path) -> str:
    matched = set(result.matched)
    projects = []
    for index, project in enumerate(profile.get("projects", [])):
        blob = normalize(" ".join(map(str, [project.get("name", ""), project.get("summary", ""), *project.get("skills", []), *project.get("bullets", [])])))
        overlap = sum(term in blob for term in matched)
        projects.append((overlap, -index, project))
    projects.sort(reverse=True, key=lambda item: (item[0], item[1]))
    lines = [f"# {profile.get('name', '姓名')}｜校招定向简历草稿", "",
             f"> 目标 JD：{jd_path.name}；关键词覆盖率：{result.score}%", "",
             "## 教育经历", ""]
    education = profile.get("education", [])
    lines.extend([f"- {item}" for item in education] or ["- 请在 profile.json 中填写真实教育经历"])
    lines += ["", "## 技能", "", "、".join(map(str, profile.get("skills", []))) or "请填写真实技能", "",
              "## 项目经历", ""]
    for _, _, project in projects:
        lines += [f"### {project.get('name', '未命名项目')}", "", str(project.get("summary", "")), ""]
        lines.extend(f"- {bullet}" for bullet in project.get("bullets", []))
        lines.append("")
    if profile.get("achievements"):
        lines += ["## 其他成果", ""]
        lines.extend(f"- {item}" for item in profile["achievements"])
    lines += ["", "<!-- 该草稿只重排用户事实，未新增雇主、指标、职责或技能。 -->", ""]
    return "\n".join(lines)


def cmd_init(args: argparse.Namespace) -> None:
    root = Path(args.dir)
    root.mkdir(parents=True, exist_ok=True)
    profile = root / "profile.json"
    store = root / "applications.json"
    if not profile.exists():
        write_json(profile, DEFAULT_PROFILE)
    if not store.exists():
        write_json(store, DEFAULT_STORE)
    (root / "jobs").mkdir(exist_ok=True)
    print(f"已初始化：{root.resolve()}\n请编辑 {profile}，再把 JD 放入 {root / 'jobs'}。")


def cmd_analyze(args: argparse.Namespace) -> None:
    profile = read_json(Path(args.profile), DEFAULT_PROFILE)
    job_path = Path(args.job)
    jd = job_path.read_text(encoding="utf-8")
    result = analyze(profile, jd)
    output = Path(args.output) if args.output else job_path.with_suffix(".analysis.md")
    output.write_text(analysis_markdown(profile, job_path, result), encoding="utf-8")
    print(f"覆盖率 {result.score}%；已匹配 {len(result.matched)} 个关键词；缺口 {len(result.gaps)} 个。\n已写入 {output}")


def cmd_tailor(args: argparse.Namespace) -> None:
    profile = read_json(Path(args.profile), DEFAULT_PROFILE)
    job_path = Path(args.job)
    result = analyze(profile, job_path.read_text(encoding="utf-8"))
    output = Path(args.output) if args.output else job_path.with_suffix(".resume.md")
    output.write_text(tailored_resume(profile, result, job_path), encoding="utf-8")
    print(f"已生成定向草稿：{output}\n请人工核验每条经历后再导出 PDF 或投递。")


def load_store(path: Path) -> dict[str, Any]:
    value = read_json(path, DEFAULT_STORE)
    value.setdefault("applications", [])
    return value


def cmd_track_add(args: argparse.Namespace) -> None:
    path = Path(args.store)
    data = load_store(path)
    item = {"id": max([x.get("id", 0) for x in data["applications"]] or [0]) + 1,
            "company": args.company, "role": args.role, "url": args.url or "",
            "status": args.status, "applied_on": args.applied_on or str(date.today()),
            "next_action": args.next_action or "", "notes": args.notes or ""}
    data["applications"].append(item)
    write_json(path, data)
    print(f"已记录投递 #{item['id']}：{item['company']} / {item['role']}")


def cmd_track_list(args: argparse.Namespace) -> None:
    data = load_store(Path(args.store))
    for item in data["applications"]:
        print(f"#{item['id']} [{item['status']}] {item['company']} / {item['role']} ({item.get('applied_on', '')})")
    if not data["applications"]:
        print("暂无投递记录")


def cmd_track_report(args: argparse.Namespace) -> None:
    items = load_store(Path(args.store))["applications"]
    counts: dict[str, int] = {}
    for item in items:
        counts[item.get("status", "未分类")] = counts.get(item.get("status", "未分类"), 0) + 1
    print(f"总投递：{len(items)}")
    for status, count in sorted(counts.items()):
        print(f"- {status}：{count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校招简历投递助手")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="初始化事实库和投递记录")
    init.add_argument("--dir", default="resume_workspace")
    init.set_defaults(func=cmd_init)
    for name, func, help_text in [("analyze", cmd_analyze, "分析 JD 与事实库的匹配度"), ("tailor", cmd_tailor, "生成定向简历草稿")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--profile", required=True)
        p.add_argument("--job", required=True)
        p.add_argument("--output")
        p.set_defaults(func=func)
    track = sub.add_parser("track", help="管理投递记录")
    track_sub = track.add_subparsers(dest="track_command", required=True)
    add = track_sub.add_parser("add", help="新增投递")
    add.add_argument("--store", default="resume_workspace/applications.json")
    add.add_argument("--company", required=True)
    add.add_argument("--role", required=True)
    add.add_argument("--url")
    add.add_argument("--status", default="待投递", choices=["待投递", "已投递", "笔试", "面试", "Offer", "拒绝", "暂停"])
    add.add_argument("--applied-on")
    add.add_argument("--next-action")
    add.add_argument("--notes")
    add.set_defaults(func=cmd_track_add)
    listing = track_sub.add_parser("list", help="列出投递")
    listing.add_argument("--store", default="resume_workspace/applications.json")
    listing.set_defaults(func=cmd_track_list)
    report = track_sub.add_parser("report", help="汇总投递状态")
    report.add_argument("--store", default="resume_workspace/applications.json")
    report.set_defaults(func=cmd_track_report)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
