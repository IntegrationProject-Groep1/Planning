#!/usr/bin/env python3
"""
XSD Contract Validation Script for Planning Messages
Validates that all Planning XSD files match the contract exactly (character-for-character).
Exits 0 on full match, 1 if any mismatch or missing file.
"""

import re
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CONTRACT_PATH = r"C:\Users\luyck\OneDrive\Documenten\Github\Planning\docs\XML_XSD_Contract_v2.3_Centralized 1 (12).md"
XSD_FOLDER    = r"C:\Users\luyck\OneDrive\Documenten\Github\Planning\xsd"

# Map each XSD filename (without extension) to (section_header_regex, label_in_contract)
# The label is used to find the FIRST ```xml block that follows the section header.
PLANNING_XSDS = {
    "session_created":        r"### 7\.1 `session_created`",
    "session_updated":        r"### 7\.2 `session_updated`",
    "session_deleted":        r"### 7\.3 `session_deleted`",
    "cancel_registration":    r"### 10\.3 `cancel_registration`",
    "session_view_request":   r"#### XSD — Request",
    "session_view_response":  r"#### XSD — Response",
    "calendar_invite":        r"#### XSD — calendar_invite \(Frontend",
    "calendar_invite_confirmed": r"#### XSD — calendar_invite_confirmed",
    "session_create_request": r"### 19\.4 `session_create_request`",
    "session_update_request": r"### 19\.5 `session_update_request`",
    "session_delete_request": r"### 19\.6 `session_delete_request`",
    "session_occupancy_update":       r"### 21\.2 `session_occupancy_update`",
    "session_registration_confirmed": r"### 21\.1 `session_registration_confirmed`",
}

def normalize(text: str) -> str:
    """Strip trailing whitespace per line and remove trailing blank lines."""
    lines = [line.rstrip() for line in text.split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)

def extract_first_xml_block_after(content: str, header_pattern: str) -> str | None:
    """Find the first ```xml...``` block after the given header pattern."""
    m = re.search(header_pattern, content)
    if not m:
        return None
    after = content[m.end():]
    block = re.search(r'```xml\n(.*?)\n```', after, re.DOTALL)
    if not block:
        return None
    return block.group(1)

def main():
    contract = Path(CONTRACT_PATH)
    xsd_dir  = Path(XSD_FOLDER)

    if not contract.exists():
        print(f"ERROR: contract not found: {contract}")
        sys.exit(1)
    if not xsd_dir.exists():
        print(f"ERROR: XSD folder not found: {xsd_dir}")
        sys.exit(1)

    content = contract.read_text(encoding='utf-8')

    print("=" * 72)
    print(" PLANNING XSD CONTRACT VALIDATION")
    print("=" * 72)

    all_ok = True

    for name, pattern in PLANNING_XSDS.items():
        xsd_file = xsd_dir / f"{name}.xsd"
        contract_xsd = extract_first_xml_block_after(content, pattern)

        if contract_xsd is None:
            print(f"\n[!!] {name}: could not find XSD block in contract (pattern: {pattern})")
            all_ok = False
            continue

        if not xsd_file.exists():
            print(f"\n[!!] {name}: XSD file MISSING — creating from contract")
            xsd_file.write_text(contract_xsd + '\n', encoding='utf-8')
            print(f"     Created: {xsd_file.name}")
            continue

        file_content = xsd_file.read_text(encoding='utf-8')

        norm_contract = normalize(contract_xsd)
        norm_file     = normalize(file_content)

        if norm_contract == norm_file:
            print(f"[OK] {name}.xsd")
        else:
            print(f"\n[!!] {name}.xsd — MISMATCH")
            contract_lines = norm_contract.split('\n')
            file_lines     = norm_file.split('\n')
            print(f"     Contract lines: {len(contract_lines)}  |  File lines: {len(file_lines)}")
            for i, (cl, fl) in enumerate(zip(contract_lines, file_lines), 1):
                if cl != fl:
                    print(f"     First diff at line {i}:")
                    print(f"       contract: {cl!r}")
                    print(f"       file:     {fl!r}")
                    break
            if len(contract_lines) != len(file_lines):
                diff = len(contract_lines) - len(file_lines)
                extra = "contract" if diff > 0 else "file"
                print(f"     {extra} has {abs(diff)} extra line(s)")
            all_ok = False

    print("\n" + "=" * 72)
    if all_ok:
        print(" ALL PLANNING XSD FILES MATCH THE CONTRACT EXACTLY")
    else:
        print(" VALIDATION FAILED — see mismatches above")
    print("=" * 72)
    sys.exit(0 if all_ok else 1)

if __name__ == '__main__':
    main()
