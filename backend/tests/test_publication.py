import subprocess

from scripts.check_publication import inspect_candidate, main


def test_force_added_private_files_are_rejected():
    for name in [".env", "data/real/source.xlsx", "docs/private/case.md", ".aws/config"]:
        assert "private/local path" in inspect_candidate(name, "")
    assert inspect_candidate(".env.example", "NOVARA_DEMO_PASSWORD=\n") == []


def test_findings_never_return_the_sensitive_value():
    value = "AK" + "IA" + "X" * 16
    assert inspect_candidate("example.py", value) == ["AWS access key"]
    registry = "123456" + "789012.dkr.ecr.us-east-2.amazonaws.com/example"
    assert inspect_candidate("docs/demo.md", registry) == ["private ECR registry"]


def test_scans_staged_content_even_if_worktree_has_been_cleaned(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "example.py"
    value = "AK" + "IA" + "X" * 16
    source.write_text(value)
    subprocess.run(["git", "add", "example.py"], cwd=tmp_path, check=True)
    source.write_text("clean")
    assert main(tmp_path) == 1
    output = capsys.readouterr().out
    assert "AWS access key" in output and value not in output
