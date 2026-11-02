#!/usr/bin/env python3
"""Secret scan for RetainAI CI, run with a pinned gitleaks binary.

  scan.py commits   scan the commits a pull request or push adds
  scan.py tree      scan the files tracked at HEAD (never ignored local files)
  scan.py selftest  prove synthetic secrets fail and clean code passes

Findings are always redacted: only rule IDs, files, lines and commits print.
Set GITLEAKS_BIN to the gitleaks executable (defaults to `gitleaks` on PATH).
"""
import argparse
import json
import os
import secrets
import string
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".gitleaks.toml"
ZERO_SHA = "0" * 40
ALNUM = string.ascii_letters + string.digits


def git(*args, cwd=REPO):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def has_commit(sha, cwd=REPO):
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=cwd, capture_output=True
    )
    return probe.returncode == 0


def run_gitleaks(mode, target, extra=(), cwd=REPO):
    """Run gitleaks with full redaction. Returns (findings, raw report text)."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [
            os.environ.get("GITLEAKS_BIN", "gitleaks"), mode, str(target),
            "--config", str(CONFIG), "--redact", "--no-banner", "--no-color",
            "--log-level", "error", "--exit-code", "1",
            "--report-format", "json", "--report-path", str(report), *extra,
        ]
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        text = report.read_text(encoding="utf-8") if report.exists() else ""
    findings = json.loads(text) if text.strip() else []
    if proc.returncode not in (0, 1) or (proc.returncode == 1 and not findings):
        # gitleaks failed to run rather than finding anything.
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"gitleaks {mode} exited {proc.returncode} without a report")
    return findings, text


def print_findings(findings):
    for f in findings:
        where = f"{f['File']}:{f['StartLine']}"
        if f.get("Commit"):
            where += f" in commit {f['Commit'][:12]}"
        print(f"  {f['RuleID']}: {where}  (fingerprint {f['Fingerprint']})")


def commit_range(event_name, event, cwd=REPO):
    """git log arguments for the commits this event adds, or None if there are none."""
    if event_name == "pull_request":
        pr = event["pull_request"]
        return f"{pr['base']['sha']}..{pr['head']['sha']}"
    if event_name == "push":
        if event.get("deleted"):
            return None
        after = event["after"]
        before = event.get("before") or ZERO_SHA
        if before != ZERO_SHA and has_commit(before, cwd):
            return f"{before}..{after}"
        # New branch, or a force push whose old tip is gone: scan every commit
        # not already on some other branch of origin.
        branch = event["ref"].removeprefix("refs/heads/")
        return f"{after} --not --exclude=origin/{branch} --remotes=origin"
    raise SystemExit(f"Unsupported event for a commit scan: {event_name}")


def scan_commits(log_opts, cwd=REPO):
    return run_gitleaks("git", cwd, ["--log-opts", log_opts], cwd=cwd)[0]


def scan_tree(cwd=REPO):
    """Scan exactly what HEAD tracks, so ignored local files (.env etc.) are never read."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.Popen(["git", "archive", "--format=tar", "HEAD"], cwd=cwd, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
            tar.extractall(tmp, filter="data")
        if archive.wait() != 0:
            raise SystemExit("git archive HEAD failed")
        return run_gitleaks("dir", ".", cwd=tmp)[0]


# --- self-test -------------------------------------------------------------

def random_text(length, alphabet=ALNUM):
    return "".join(secrets.choice(alphabet) for _ in range(length))


def synthetic_fixtures():
    """Fresh random secrets each run; the literals are split so this file never matches."""
    meta = "EAA" + secrets.choice("123456789") + random_text(180)  # shape of the 2025 leak
    stripe = "sk_" + "live_" + random_text(40)
    pem = "\n".join(random_text(64, ALNUM + "+/") for _ in range(8))
    key = "-----BEGIN " + "PRIVATE KEY-----\n" + pem + "\n-----END " + "PRIVATE KEY-----\n"
    return [
        ("meta-graph-access-token", "whatsapp_settings.py", f'WHATSAPP_TOKEN = "{meta}"\n', meta),
        ("stripe-access-token", "billing.env", f"STRIPE_SECRET_KEY={stripe}\n", stripe),
        ("private-key", "signing.pem", key, pem.splitlines()[0]),
    ]


CLEAN_SOURCE = (
    "import os\n"
    'WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")\n'
    'STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")\n'
    'EXAMPLE = "EAA... paste your token in Render, never in code"\n'
)


def check(results, name, ok, detail=""):
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")


def check_redacted(results, name, findings, report, secret):
    redacted = secret not in report and all(f.get("Secret") == "REDACTED" for f in findings)
    check(results, f"{name} is redacted in the report", redacted)


def selftest_files(results):
    for rule, filename, content, secret in synthetic_fixtures():
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, filename).write_text(content, encoding="utf-8")
            findings, report = run_gitleaks("dir", ".", cwd=tmp)
        rules = sorted({f["RuleID"] for f in findings})
        check(results, f"synthetic {rule} fails the scan", rule in rules, ", ".join(rules) or "no findings")
        check_redacted(results, f"synthetic {rule}", findings, report, secret)
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "settings.py").write_text(CLEAN_SOURCE, encoding="utf-8")
        findings, _ = run_gitleaks("dir", ".", cwd=tmp)
    check(results, "clean code passes", not findings, f"{len(findings)} findings")


def selftest_history(results):
    """A leak committed then deleted on a branch must still fail the commit scan."""
    rule, filename, content, secret = synthetic_fixtures()[0]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        origin, work = Path(tmp, "origin.git"), Path(tmp, "work")
        git("init", "--quiet", "--bare", str(origin), cwd=tmp)
        git("init", "--quiet", "-b", "deploy", str(work), cwd=tmp)

        def commit(message):
            git("-c", "user.name=scan", "-c", "user.email=scan@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", message, cwd=work)
            return git("rev-parse", "HEAD", cwd=work)

        def push(branch):
            git("push", "--quiet", "origin", branch, cwd=work)
            git("fetch", "--quiet", "origin", cwd=work)

        git("remote", "add", "origin", str(origin), cwd=work)
        Path(work, "app.py").write_text(CLEAN_SOURCE, encoding="utf-8")
        git("add", ".", cwd=work)
        base = commit("base")
        push("deploy")

        git("switch", "--quiet", "-c", "fix/leak", cwd=work)
        Path(work, filename).write_text(content, encoding="utf-8")
        git("add", ".", cwd=work)
        commit("add settings")
        git("rm", "--quiet", filename, cwd=work)
        head = commit("remove settings")
        push("fix/leak")

        def scan(event_name, event):
            opts = commit_range(event_name, event, cwd=work)
            findings = scan_commits(opts, cwd=work)
            return sorted({f["RuleID"] for f in findings})

        new_branch = scan("push", {"before": ZERO_SHA, "after": head, "ref": "refs/heads/fix/leak"})
        check(results, "new-branch push finds a leak deleted later", rule in new_branch, ", ".join(new_branch) or "no findings")
        lost_tip = scan("push", {"before": "f" * 40, "after": head, "ref": "refs/heads/fix/leak"})
        check(results, "force push with an unknown old tip finds it", rule in lost_tip, ", ".join(lost_tip) or "no findings")
        pull = scan("pull_request", {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}})
        check(results, "pull request range finds it", rule in pull, ", ".join(pull) or "no findings")
        tree = sorted({f["RuleID"] for f in scan_tree(cwd=work)})
        check(results, "tree scan alone misses it (why commits are scanned)", not tree, ", ".join(tree) or "no findings")

        git("switch", "--quiet", "deploy", cwd=work)
        Path(work, "README.md").write_text("RetainAI\n", encoding="utf-8")
        git("add", ".", cwd=work)
        after = commit("docs")
        push("deploy")
        clean = scan("push", {"before": base, "after": after, "ref": "refs/heads/deploy"})
        check(results, "clean push to deploy passes", not clean, ", ".join(clean) or "no findings")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["commits", "tree", "selftest"])
    mode = parser.parse_args().mode

    if mode == "selftest":
        results = []
        selftest_files(results)
        selftest_history(results)
        print(f"{sum(results)}/{len(results)} scanner checks passed")
        return 0 if all(results) else 1

    if mode == "commits":
        event_name = os.environ["GITHUB_EVENT_NAME"]
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        log_opts = commit_range(event_name, event)
        if log_opts is None:
            print("No commits to scan.")
            return 0
        print(f"Scanning commits: {log_opts}")
        findings = scan_commits(log_opts)
        advice = ("Rewrite the branch so no commit contains the value, and rotate it if it is real. "
                  "A later commit that deletes it is not enough.")
    else:
        findings = scan_tree()
        advice = "Remove the value from the file, and rotate it if it is real."

    if not findings:
        print("No secrets found.")
        return 0
    print(f"{len(findings)} possible secrets found (values redacted):")
    print_findings(findings)
    print(advice)
    print("If one is a false positive, add its fingerprint to .gitleaksignore.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
