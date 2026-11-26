"""Publish a reviewed incident summary from the local operator's terminal."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from triage.domain import CAUSES

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
INCIDENT = re.compile(r"[a-f0-9]{20}")


def issue_payload(report: Path) -> dict[str, str]:
    if not INCIDENT.fullmatch(report.stem) or report.suffix != ".md":
        raise ValueError("Expected a generated incident filename")
    document = report.read_text(encoding="utf-8")
    match = re.search(r"^<!-- triage-eval (.+) -->$", document, re.MULTILINE)
    if not match:
        raise ValueError("Report is missing investigation metadata")
    ranks = json.loads(match[1])["hypotheses"]
    if not isinstance(ranks, list):
        raise ValueError("Report has invalid hypotheses")
    causes = []
    for row in ranks[:3]:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str):
            raise ValueError("Report has invalid hypotheses")
        if row[0] not in CAUSES:
            raise ValueError("Report contains an unknown cause")
        causes.append(CAUSES[row[0]].title)
    summary = "\n".join(f"- {cause}" for cause in causes) or "- No supported hypothesis."
    return {
        "title": f"Incident {report.stem}: {causes[0] if causes else 'Investigation'}",
        "body": (f"Incident ID: `{report.stem}`\n\n## Ranked causes\n\n{summary}"
                 "\n\nReview the local incident report before taking action.\n"),
    }


def publish(repo: str, token: str, payload: dict[str, str]) -> str:
    if not REPOSITORY.fullmatch(repo) or any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError("Expected a GitHub repository in OWNER/REPO form")
    request = Request(f"https://api.github.com/repos/{repo}/issues",
                      data=json.dumps(payload).encode(),
                      headers={"Authorization": f"Bearer {token}",
                               "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json",
                               "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=15) as response:
        url = json.load(response)["html_url"]
    if not isinstance(url, str):
        raise ValueError("GitHub returned an invalid issue URL")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--repo", required=True, metavar="OWNER/REPO")
    parser.add_argument("--publish", action="store_true", help="Create the issue on GitHub")
    args = parser.parse_args()
    try:
        payload = issue_payload(args.report)
        if args.publish:
            token = os.getenv("GITHUB_TOKEN")
            if not token:
                parser.error("GITHUB_TOKEN is required to publish")
            print(publish(args.repo, token, payload))
        else:
            print(json.dumps(payload, indent=2))
    except HTTPError as exc:
        parser.exit(1, f"GitHub rejected the issue request (HTTP {exc.code}).\n")
    except URLError as exc:
        parser.exit(1, f"GitHub issue request failed: {exc.reason}\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
