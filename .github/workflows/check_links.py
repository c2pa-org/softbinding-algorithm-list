#!/usr/bin/env python3
"""
check_links.py

Scans the softbinding algorithm list and validates its external links.
Exports summary to GITHUB_STEP_SUMMARY and a JSON report to link_check_report.json.

Links are classified as ok, broken, blocked, or unreachable. Only HTTP 404
and 410 responses are treated as confirmed broken links.

Usage:
    python check_links.py --file path/to/file.json [--timeout 15] [--retries 2]
"""
import argparse
import json
import os
import sys
import time

import requests

# Status codes that typically indicate bot/WAF blocking rather than a dead link.
BLOCKED_CODES = {401, 403, 429, 999}
BROKEN_CODES = {404, 410}

# Headers that mimic a real browser request. 
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def extract_urls(entries):
    """Return URLs together with their algorithm and source field."""
    result = []
    for entry in entries:
        algorithm = entry.get("alg", "<unknown>")
        metadata = entry.get("entryMetadata", {})
        candidates = [
            ("informationalUrl", metadata.get("informationalUrl")),
            *(
                ("softBindingResolutionApis", url)
                for url in entry.get("softBindingResolutionApis", [])
            ),
        ]
        for field, url in candidates:
            if url:
                result.append({"algorithm": algorithm, "field": field, "url": url})
    return result


def check_url(url, timeout, retries):
    """
    Returns (state, status, error) where state is one of:
      "ok"      - link is reachable
      "blocked" - site responded with a bot-protection style status code
      "broken"  - resource is confirmed absent (HTTP 404 or 410)
      "unreachable" - server or network failure prevents verification
    """
    for attempt in range(retries + 1):
        try:
            # Use GET (not HEAD) since many bot-protection layers block or
            # mishandle HEAD requests outright.
            with requests.get(
                url, allow_redirects=True, timeout=timeout, headers=HEADERS, stream=True
            ) as response:
                status = response.status_code
            if status < 400:
                return "ok", status, None
            if status in BROKEN_CODES:
                state = "broken"
                error = f"HTTP {status}"
            elif status in BLOCKED_CODES:
                state = "blocked"
                error = f"HTTP {status} (site may be blocking automated requests)"
            else:
                state = "unreachable"
                error = f"HTTP {status}"
        except requests.RequestException as e:
            state = "unreachable"
            status = None
            error = str(e)

        if attempt < retries:
            time.sleep(3 * (attempt + 1))  # back off a bit longer each retry

    return state, status, error


def markdown_table(items):
    lines = ["| Algorithm | Field | URL | Result |", "|---|---|---|---|"]
    for item in items:
        values = (
            item["algorithm"],
            item["field"],
            item["url"],
            item["error"],
        )
        escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to the file containing links to check")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"::error::File not found: {args.file}")
        sys.exit(2)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        print(f"::error::Could not read algorithm list: {error}")
        sys.exit(2)

    if not isinstance(entries, list):
        print("::error::Algorithm list must be a JSON array")
        sys.exit(2)

    links = extract_urls(entries)
    if not links:
        print("::error::No URLs found in the algorithm list")
        sys.exit(2)
    print(f"Found {len(links)} URL reference(s) in {args.file}")

    results = []
    broken = []
    blocked = []
    unreachable = []

    checked_urls = {}
    for link in links:
        url = link["url"]
        if url not in checked_urls:
            checked_urls[url] = check_url(url, args.timeout, args.retries)
        state, status, error = checked_urls[url]
        result = {**link, "state": state, "status": status, "error": error}
        results.append(result)
        print(f"[{state.upper()}] {url} ({status or error})")
        if state == "broken":
            broken.append(result)
        elif state == "blocked":
            blocked.append(result)
        elif state == "unreachable":
            unreachable.append(result)

    with open("link_check_report.json", "w") as f:
        json.dump({"file": args.file, "results": results}, f, indent=2)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## Link check results for `{args.file}`\n\n")
            f.write(
                f"Checked {len(links)} link(s): {len(broken)} broken, "
                f"{len(blocked)} blocked, and {len(unreachable)} unreachable.\n\n"
            )
            for title, items in (
                ("Broken", broken),
                ("Blocked (please verify manually)", blocked),
                ("Unreachable (please retry or verify manually)", unreachable),
            ):
                if items:
                    f.write(f"### {title}\n\n{markdown_table(items)}\n\n")

    if blocked:
        print(f"::warning::{len(blocked)} link(s) returned bot-protection style responses; verify manually.")
    if unreachable:
        print(f"::warning::{len(unreachable)} link(s) could not be verified; retry or verify manually.")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(f"result={'broken' if broken else 'healthy'}\n")
            f.write(f"unverified={'true' if blocked or unreachable else 'false'}\n")

    if broken:
        print(f"::error::{len(broken)} broken link(s) found in {args.file}")
        sys.exit(1)

    print("No confirmed broken links found; see the summary for unverifiable links.")
    sys.exit(0)


if __name__ == "__main__":
    main()
