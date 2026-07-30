#!/usr/bin/env python3
"""Reject credential-like data from Git-tracked release content."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    line: int | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: {self.rule}"


FORBIDDEN_FILE_NAMES = {
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}
FORBIDDEN_SUFFIXES = {".pem", ".p12", ".pfx", ".ppk"}
TEXT_RULES = {
    "private key material": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "GitHub access token": re.compile(
        r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
    ),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Tencent Cloud secret id": re.compile(r"\bAKID[A-Za-z0-9]{16,}\b"),
    "OpenAI-style secret key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "WeChat AppID": re.compile(r"\bwx[0-9a-fA-F]{16}\b"),
}
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?im)^[ \t]*(?:export[ \t]+)?"
    r"(SMARTBAG_UPLOAD_TOKEN|SMARTBAG_ALERT_PHONE|WECHAT_APPID|WECHAT_APPSECRET|"
    r"SS928_BOARD_PASSWORD|TENCENT_SECRET_ID|TENCENT_SECRET_KEY|AWS_ACCESS_KEY_ID|"
    r"AWS_SECRET_ACCESS_KEY)[ \t]*[:=][ \t]*([^#\r\n]*)$"
)
SAFE_TEMPLATE_VALUES = {"", '""', "''", "...", "<required>", "<set-locally>"}
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".h", ".hpp", ".ini", ".js", ".json", ".md",
    ".py", ".service", ".sh", ".toml", ".txt", ".wxml", ".wxss", ".yaml", ".yml",
}


def release_candidate_files(repo_root: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "-C", str(repo_root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    )
    return [item.decode("utf-8") for item in output.split(b"\0") if item]


def is_test_fixture(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return "tests" in parts or path.startswith("07_tests/")


def scan(repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative in release_candidate_files(repo_root):
        path = repo_root / PurePosixPath(relative)
        lower_name = path.name.lower()
        suffix = path.suffix.lower()
        if lower_name in FORBIDDEN_FILE_NAMES or suffix in FORBIDDEN_SUFFIXES:
            findings.append(Finding(relative, "credential file must not be tracked"))
            continue
        if lower_name == ".env" or (lower_name.startswith(".env.") and not lower_name.endswith(".example")):
            findings.append(Finding(relative, "non-template environment file must not be tracked"))
            continue
        if suffix not in TEXT_SUFFIXES and lower_name not in {"makefile", "dockerfile"} and not lower_name.endswith(".env.example"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for rule, pattern in TEXT_RULES.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(Finding(relative, rule, line))
        if is_test_fixture(relative):
            continue
        for match in SENSITIVE_ASSIGNMENT.finditer(text):
            value = match.group(2).strip().rstrip(",")
            if value in SAFE_TEMPLATE_VALUES:
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(relative, f"non-empty sensitive setting {match.group(1)}", line))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    findings = scan(repo_root)
    if findings:
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        print(f"FAIL: {len(findings)} tracked credential finding(s)", file=sys.stderr)
        return 1
    print(
        f"PASS: scanned {len(release_candidate_files(repo_root))} Git release-candidate paths; "
        "no blocked credentials found"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
