"""Check Git publication candidates without printing matching sensitive values."""

import re
import subprocess
from pathlib import Path, PurePosixPath

PRIVATE_PATHS = {
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "docs/aws-support-draft.txt",
}
PRIVATE_PARTS = {".aws", ".codex", ".agents", ".vscode", "secrets", "node_modules", ".venv"}
PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "AWS project ARN": re.compile(r"arn:aws[^:]*:[^\s:]+:[^\s:]*:[0-9]{12}:"),
    "private ECR registry": re.compile(r"\b[0-9]{12}\.dkr\.ecr\."),
    "signed URL": re.compile(r"(?i)X-Amz-(?:Credential|Signature)="),
}


def inspect_candidate(name: str, content: str) -> list[str]:
    path = PurePosixPath(name)
    findings = []
    if (
        name in PRIVATE_PATHS
        or PRIVATE_PARTS.intersection(path.parts)
        or name.startswith(("data/real/", "docs/private/", "evals/runs/"))
        or path.suffix in {".db", ".sqlite", ".sqlite3", ".key", ".pem"}
        or (path.name.startswith(".env") and path.name != ".env.example")
        or (path.suffix in {".xlsx", ".xls", ".csv"} and not name.startswith("data/synthetic/"))
    ):
        findings.append("private/local path")
    findings.extend(label for label, pattern in PATTERNS.items() if pattern.search(content))
    return findings


def main(root=None):
    root = root or Path(__file__).resolve().parents[1]
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    )
    names = sorted(set(output.decode().strip("\0").split("\0")) - {""})
    indexed = set(
        subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=root)
        .decode()
        .strip("\0")
        .split("\0")
    )
    blocked = []
    for name in names:
        path = root / name
        contents = []
        if name in indexed:
            contents.append(subprocess.check_output(["git", "show", f":{name}"], cwd=root))
        if path.is_symlink():
            blocked.append((name, "symlink requires manual review"))
        elif path.is_file():
            contents.append(path.read_bytes())
        findings = set()
        for content in contents:
            findings.update(inspect_candidate(name, content.decode("utf-8", errors="replace")))
        blocked.extend((name, label) for label in sorted(findings))
    for name, label in blocked:
        print(f"BLOCKED {name}: {label}")
    print(f"Checked {len(names)} Git candidates; {len(blocked)} findings.")
    return int(bool(blocked))


if __name__ == "__main__":
    raise SystemExit(main())
