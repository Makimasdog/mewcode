"""Deterministic checks for paper-reproduction artifacts.

The paper workflow deliberately uses an LLM for source reading and coding, but
its final verdict must not depend on prose such as ``VERDICT: PASS``.  This
module performs a small, dependency-free audit over the files a worker leaves
under ``paper_repro``.  It is intentionally conservative: when no protocol
artifact is present it does nothing, so ordinary DAGs and unit-test doubles are
unaffected.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditFinding:
    code: str
    message: str


@dataclass
class PaperAuditReport:
    root: Path | None = None
    findings: list[AuditFinding] = field(default_factory=list)
    observed: dict[str, Any] = field(default_factory=dict)

    @property
    def checked(self) -> bool:
        return self.root is not None

    @property
    def passed(self) -> bool:
        return self.checked and not self.findings

    def render(self) -> str:
        if not self.checked:
            return "PAPER AUDIT: NOT RUN (no protocol artifact found)"
        lines = [f"PAPER AUDIT: {'PASS' if self.passed else 'FAIL'}", f"ROOT: {self.root}"]
        if self.observed:
            lines.append("OBSERVED: " + json.dumps(self.observed, ensure_ascii=False, sort_keys=True))
        lines.extend(f"{finding.code}: {finding.message}" for finding in self.findings)
        return "\n".join(lines)


def audit_paper_artifacts(
    work_dir: str | Path, *, artifact_root: Path | None = None
) -> PaperAuditReport:
    """Audit the newest direct ``paper_repro/*/protocol.md`` artifact.

    The direct path is intentional. Runtime snapshots under ``.mewcode`` may
    contain old experiments and must not unexpectedly change the verdict of a
    new run. A caller can run this function again with that snapshot directory
    when explicitly auditing historical evidence.
    """
    base = Path(work_dir)
    candidates = [artifact_root] if artifact_root is not None else [
        path.parent
        for path in (base / "paper_repro").glob("*/protocol.md")
        if path.is_file()
    ]
    # A workspace can contain artifacts from earlier attempts. Pick the
    # candidate with the newest artifact (protocol or result), which is the
    # one the current Verification node just produced in normal operation.
    roots = sorted(candidates, key=_root_mtime, reverse=True)
    if not roots:
        return PaperAuditReport()
    root = roots[0]
    report = PaperAuditReport(root=root)
    protocol = (root / "protocol.md").read_text(encoding="utf-8", errors="replace")

    expected_distances = _distance_expectations(protocol)
    if len(expected_distances) > 1:
        report.findings.append(
            AuditFinding(
                "PROTOCOL_CONFLICT",
                f"protocol contains conflicting distance-calculation expectations: {expected_distances}",
            )
        )
    expected_distance = expected_distances[0] if len(expected_distances) == 1 else None
    _validate_protocol_math(protocol, report)

    json_files = sorted(root.rglob("*.json"))
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in json_files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        def collect(item: Any) -> None:
            if isinstance(item, dict):
                metric_keys = {"distance_calculations", "counts", "cluster_counts",
                               "counts_per_cluster", "assignments", "labels", "algorithm_compliance"}
                if metric_keys.intersection(item):
                    records.append((path, item))
                for child in item.values():
                    if isinstance(child, dict):
                        collect(child)
        collect(value)

    distance_values = _values(records, "distance_calculations")
    count_lists = _list_values(records, ("counts", "cluster_counts", "counts_per_cluster"))
    data_rows = _numeric_values(records, ("data_rows", "n_samples", "sample_count"))
    assignment_lengths = _list_lengths(records, ("assignments", "labels"))
    data_rows = sorted(set(data_rows + assignment_lengths))
    compliance_values = _values(records, "algorithm_compliance")
    report.observed.update(
        expected_distance=expected_distance,
        distance_calculations=distance_values,
        count_sums=[sum(item) for item in count_lists],
        data_rows=data_rows,
        algorithm_compliance=compliance_values,
    )

    if not records:
        report.findings.append(AuditFinding("NO_RESULTS", "no JSON result artifact was found"))
        return report

    if expected_distance is not None and (not distance_values or any(value != expected_distance for value in distance_values)):
        report.findings.append(
            AuditFinding(
                "DISTANCE_MISMATCH",
                f"observed {distance_values}, protocol requires {expected_distance}",
            )
        )

    for record in records:
        local_rows = _numeric_values([record], ("data_rows", "n_samples", "sample_count"))
        local_rows += _list_lengths([record], ("assignments", "labels"))
        for counts in _list_values([record], ("counts", "cluster_counts", "counts_per_cluster")):
            if any(sum(counts) != rows for rows in local_rows):
                report.findings.append(
                    AuditFinding(
                        "COUNT_MISMATCH",
                        f"cluster-count sum {sum(counts)} does not match data-row count {local_rows}",
                    )
                )

    if compliance_values and expected_distance is not None:
        actual_compliant = bool(distance_values) and all(
            value == expected_distance for value in distance_values
        )
        if any(bool(value) != actual_compliant for value in compliance_values):
            report.findings.append(
                AuditFinding(
                    "COMPLIANCE_MISMATCH",
                    f"reported algorithm_compliance={compliance_values}, independently derived {actual_compliant}",
                )
            )
    return report


def _distance_expectations(protocol: str) -> list[int]:
    values = re.findall(
        r"(?:exactly|expected(?:\s+to\s+be)?|requires?)\s+(\d+)\s+distance\s+calculations",
        protocol,
        re.I,
    )
    values += re.findall(
        r"distance[\s_]+calculations\s*[:=]\s*(\d+)", protocol, re.I
    )
    return sorted({int(value) for value in values})


def _validate_protocol_math(protocol: str, report: PaperAuditReport) -> None:
    """Catch self-contradictory protocols before judging implementation output."""
    sample_match = re.search(r"(?:generate|process|input)[^\n]{0,80}?\b(\d{2,})\s+samples?\b", protocol, re.I)
    k_match = re.search(r"\bk\s*[=:]\s*(\d+)\b", protocol, re.I)
    if sample_match is None or k_match is None:
        return
    samples = int(sample_match.group(1))
    k = int(k_match.group(1))
    expected = _distance_expectations(protocol)
    if len(expected) != 1 or k <= 1 or samples <= k:
        return
    # With first-k initialization, each remaining point is compared with k
    # centroids. A protocol that calls the point count itself the exact number
    # of distance calculations is mixing two different units.
    if expected[0] == samples and re.search(
        r"first\s+k|initialize[^\n]{0,80}first\s+\w*\s* samples|single[- ]pass",
        protocol,
        re.I,
    ):
        report.findings.append(
            AuditFinding(
                "PROTOCOL_SEMANTIC_ERROR",
                f"{samples} samples with k={k} and first-k single-pass initialization cannot require exactly {samples} centroid-distance calculations",
            )
        )


def _root_mtime(root: Path) -> float:
    paths = [root / "protocol.md", *root.rglob("*.json")]
    return max((path.stat().st_mtime for path in paths if path.is_file()), default=0.0)


def _values(records: list[tuple[Path, dict[str, Any]]], key: str) -> list[Any]:
    return [value[key] for _, value in records if key in value and isinstance(value[key], (int, float, bool))]


def _numeric_values(records: list[tuple[Path, dict[str, Any]]], keys: tuple[str, ...]) -> list[int]:
    result: list[int] = []
    for _, record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result.append(int(value))
    return sorted(set(result))


def _list_values(records: list[tuple[Path, dict[str, Any]]], keys: tuple[str, ...]) -> list[list[int]]:
    result: list[list[int]] = []
    for _, record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, list) and value and all(isinstance(item, int) for item in value):
                result.append([int(item) for item in value])
    return result


def _list_lengths(records: list[tuple[Path, dict[str, Any]]], keys: tuple[str, ...]) -> list[int]:
    result: list[int] = []
    for _, record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, list) and value:
                result.append(len(value))
    return result
