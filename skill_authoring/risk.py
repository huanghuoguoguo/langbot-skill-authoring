from __future__ import annotations

import re

from .models import RiskFinding, RiskReport


SECRET_PATTERNS = [
    ("secret.openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("secret.github_token", re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b")),
    ("secret.jwt", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("secret.generic_assignment", re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]{8,}")),
]

INTERNAL_URL_RE = re.compile(r"\bhttps?://(?:localhost|127\.0\.0\.1|10\.|172\.(?:1[6-9]|2\d|3[0-1])\.|192\.168\.)[^\s)]+")
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])/(?:home|Users|var|etc|tmp)/[^\s`'\"),]+")
DANGEROUS_COMMAND_RE = re.compile(r"\b(rm\s+-rf|chmod\s+777|curl\s+[^|;\n]+?\|\s*(?:bash|sh)|wget\s+[^|;\n]+?\|\s*(?:bash|sh)|docker\s+run\s+--privileged)\b")


def scan_text(text: str) -> RiskReport:
    findings: list[RiskFinding] = []
    for code, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(
                RiskFinding(
                    severity="blocker",
                    code=code,
                    message="Potential secret or credential appears in the candidate text.",
                )
            )
    if INTERNAL_URL_RE.search(text):
        findings.append(
            RiskFinding(
                severity="warn",
                code="environment.internal_url",
                message="Internal or local URL should be generalized before publishing.",
            )
        )
    if ABSOLUTE_PATH_RE.search(text):
        findings.append(
            RiskFinding(
                severity="warn",
                code="environment.absolute_path",
                message="Absolute machine-local paths should be replaced with variables or relative paths.",
            )
        )
    if DANGEROUS_COMMAND_RE.search(text):
        findings.append(
            RiskFinding(
                severity="blocker",
                code="command.dangerous",
                message="Dangerous shell command pattern requires human review.",
            )
        )

    status = "pass"
    if any(item.severity == "blocker" for item in findings):
        status = "blocked"
    elif findings:
        status = "warn"
    return RiskReport(status=status, findings=findings)

