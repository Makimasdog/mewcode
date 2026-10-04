from __future__ import annotations

import json
from pathlib import Path

from mewcode.paper_audit import audit_paper_artifacts


def _write_artifacts(root: Path, *, distance: int, counts: list[int], compliant: bool) -> None:
    paper = root / "paper_repro" / "demo"
    (paper / "results").mkdir(parents=True)
    (paper / "protocol.md").write_text(
        "# Protocol\n- exactly 1000 distance calculations\n", encoding="utf-8"
    )
    (paper / "results" / "result.json").write_text(
        json.dumps(
            {
                "data_rows": 1000,
                "counts": counts,
                "distance_calculations": distance,
                "algorithm_compliance": compliant,
            }
        ),
        encoding="utf-8",
    )


def test_audit_rejects_self_reported_pass_with_inconsistent_artifacts(tmp_path: Path) -> None:
    _write_artifacts(tmp_path, distance=3000, counts=[500, 503], compliant=True)

    report = audit_paper_artifacts(tmp_path)

    assert report.checked
    assert not report.passed
    assert {finding.code for finding in report.findings} == {
        "DISTANCE_MISMATCH",
        "COUNT_MISMATCH",
        "COMPLIANCE_MISMATCH",
    }


def test_audit_accepts_consistent_artifacts(tmp_path: Path) -> None:
    _write_artifacts(tmp_path, distance=1000, counts=[500, 500], compliant=True)

    report = audit_paper_artifacts(tmp_path)

    assert report.passed
    assert "PAPER AUDIT: PASS" in report.render()


def test_audit_rejects_conflicting_protocol_requirements(tmp_path: Path) -> None:
    paper = tmp_path / "paper_repro" / "conflict"
    (paper / "results").mkdir(parents=True)
    (paper / "protocol.md").write_text(
        "exactly 1000 distance calculations\n"
        "distance calculations: 3000\n",
        encoding="utf-8",
    )
    (paper / "results" / "result.json").write_text(
        json.dumps({"distance_calculations": 1000}), encoding="utf-8"
    )

    report = audit_paper_artifacts(tmp_path)

    assert "PROTOCOL_CONFLICT" in {finding.code for finding in report.findings}


def test_audit_rejects_semantically_impossible_distance_requirement(tmp_path: Path) -> None:
    paper = tmp_path / "paper_repro" / "semantic"
    paper.mkdir(parents=True)
    (paper / "protocol.md").write_text(
        "Generate 1000 samples.\n"
        "k=3. Initialize centroids using first k samples.\n"
        "Single-pass: exactly 1000 distance calculations.\n",
        encoding="utf-8",
    )

    report = audit_paper_artifacts(tmp_path)

    assert "PROTOCOL_SEMANTIC_ERROR" in {finding.code for finding in report.findings}
