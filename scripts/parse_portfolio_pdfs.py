from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from pypdf import PdfReader


CALIBRATION_IDS = {"SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-009"}


def _clean_page(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "Northstar Medical Devices - Synthetic ITRA Proof-of-Concept":
            continue
        if re.fullmatch(r"Page \d+", stripped):
            continue
        if stripped.startswith("6. ITRA Controls"):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _paragraph(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _control_blocks(reader: PdfReader, catalog: list[dict]) -> list[dict]:
    controls_text = "\n".join(_clean_page(reader.pages[index].extract_text() or "") for index in range(5, 11))
    ids = [item["control_id"] for item in catalog]
    controls = []
    for index, control_id in enumerate(ids):
        start = re.search(rf"(?m)^{re.escape(control_id)}\s*$", controls_text)
        if not start:
            raise ValueError(f"Control {control_id} not found")
        if index + 1 < len(ids):
            end = re.search(rf"(?m)^{re.escape(ids[index + 1])}\s*$", controls_text[start.end():])
            if not end:
                raise ValueError(f"Control boundary after {control_id} not found")
            block = controls_text[start.end():start.end() + end.start()]
        else:
            block = controls_text[start.end():]
        match = re.search(
            r"Status\s*\n(?P<status>.*?)\nType\s*\n(?P<type>.*?)\nDetailed Description\s*\n"
            r"(?P<description>.*?)\nImplementation\s*\nConsiderations\s*\n(?P<implementation>.*)\Z",
            block,
            re.DOTALL,
        )
        if not match:
            raise ValueError(f"Could not parse fields for {control_id}")
        catalog_item = catalog[index]
        controls.append({
            "control_id": control_id,
            "control_text": catalog_item["control_text"],
            "status_raw": _paragraph(match.group("status")),
            "type": _paragraph(match.group("type")),
            "detailed_description": _paragraph(match.group("description")),
            "implementation_considerations": _paragraph(match.group("implementation")),
        })
    return controls


def parse_pdf(pdf_path: Path, catalog: list[dict], truth_site: dict) -> dict:
    reader = PdfReader(pdf_path)
    if len(reader.pages) != 13:
        raise ValueError(f"Expected 13 pages in {pdf_path.name}, found {len(reader.pages)}")
    site_id = truth_site["itra_id"]
    site_name = truth_site["site"]
    return {
        "site_id": site_id,
        "site_name": site_name,
        "business_application": truth_site["system_name"],
        "application_id": f"NMD-ORA-{site_id[-3:]}",
        "itra_version": "1.0",
        "type": "Manufacturing Equipment / IT-OT System",
        "major_event": "Initial synthetic assessment",
        "description": (
            "Local deployment of the standardized Orion Automated Assembly Line. The core equipment "
            "architecture is common across all ten fictional locations; this assessment records the "
            f"implementation choices made at {site_name}."
        ),
        "state": "Approved for synthetic analytics testing",
        "location": site_name,
        "portfolio_cohort": "Calibration" if site_id in CALIBRATION_IDS else "Validation",
        "controls": _control_blocks(reader, catalog),
        "ground_truth_normalized": truth_site["normalized"],
        "ground_truth_evidence": truth_site["evidence"],
        "security_outlier": truth_site["security_outlier"],
        "deliberately_ambiguous": truth_site["deliberately_ambiguous"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse the synthetic portfolio PDFs into fixture JSON.")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/parsed"))
    parser.add_argument("--catalog", type=Path, default=Path("data/control_catalog.json"))
    parser.add_argument("--ground-truth", type=Path, required=True)
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    truth_by_id = {site["itra_id"]: site for site in ground_truth["sites"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for pdf_path in sorted(args.source_dir.glob("SYN_ITRA_*.pdf")):
        match = re.search(r"SYN_ITRA_(\d{3})_", pdf_path.name)
        if not match:
            continue
        site_id = f"SYN-{match.group(1)}"
        if site_id not in truth_by_id:
            raise ValueError(f"No ground truth found for {site_id}")
        payload = parse_pdf(pdf_path, catalog, truth_by_id[site_id])
        output_path = args.output_dir / f"{site_id}.json"
        if output_path.exists():
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("security_answers"):
                print(f"Preserved richer reference fixture {output_path.name}")
                continue
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
    print(f"Parsed {written} portfolio PDFs into {args.output_dir}")


if __name__ == "__main__":
    main()
