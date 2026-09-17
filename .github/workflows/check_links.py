#!/usr/bin/env python3
"""
check_links.py

Scans the softbinging-algorithm-list json and validates "informationalUrl" links.
Exports summary to GITHUB_STEP_SUMMARY and a JSON report to link_check_report.json.

Links that respond with a status commonly used by bot-protection services
(403, 429, 999) are reported separately as "blocked" rather than "broken".

Usage:
    python check_links.py --file path/to/file.md [--timeout 15] [--retries 2]
"""
import argparse
import json
import os
import re
import sys
import time

import requests

# Matches the value of an "informationalUrl" key, e.g.:
#   "informationalUrl": "https://example.com/page"
INFORMATIONAL_URL_RE = re.compile(r'"informationalUrl"\s*:\s*"(https?://[^"]+)"')

# Status codes that typically indicate bot/WAF blocking rather than a dead link.
SOFT_FAIL_CODES = {403, 429, 999}

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


def extract_urls(text):
    urls = INFORMATIONAL_URL_RE.findall(text)
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def check_url(url, timeout, retries):
    """
    Returns (state, status, error) where state is one of:
      "ok"      - link is reachable
      "blocked" - site responded with a bot-protection style status code
      "broken"  - link genuinely appears dead
    """
    last_status = None
    last_error = None

    for attempt in range(retries + 1):
        try:
            # Use GET (not HEAD) since many bot-protection layers block or
            # mishandle HEAD requests outright.
            resp = requests.get(
                url, allow_redirects=True, timeout=timeout, headers=HEADERS, stream=True
            )
            status = resp.status_code
            if status < 400:
                return "ok", status, None

            last_status = status
            if status in SOFT_FAIL_CODES:
                last_error = f"HTTP {status} (site may be blocking automated requests)"
            else:
                last_error = f"HTTP {status}"
        except requests.RequestException as e:
            last_error = str(e)

        if attempt < retries:
            time.sleep(3 * (attempt + 1))  # back off a bit longer each retry

    if last_status in SOFT_FAIL_CODES:
        return "blocked", last_status, last_error
    return "broken", last_status, last_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to the file containing links to check")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"::error::File not found: {args.file}")
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    urls = extract_urls(text)
    print(f"Found {len(urls)} unique URL(s) in {args.file}")

    results = []
    broken = []
    blocked = []

    for url in urls:
        state, status, error = check_url(url, args.timeout, args.retries)
        results.append({"url": url, "state": state, "status": status, "error": error})
        print(f"[{state.upper()}] {url} ({status or error})")
        if state == "broken":
            broken.append({"url": url, "error": error})
        elif state == "blocked":
            blocked.append({"url": url, "error": error})

    with open("link_check_report.json", "w") as f:
        json.dump({"file": args.file, "results": results}, f, indent=2)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## Link check results for `{args.file}`\n\n")
            f.write(
                f"Checked {len(urls)} link(s). {len(broken)} broken, "
                f"{len(blocked)} possibly blocked by bot protection.\n\n"
            )
            if broken:
                f.write("### Broken\n\n| URL | Error |\n|---|---|\n")
                for b in broken:
                    f.write(f"| {b['url']} | {b['error']} |\n")
                f.write("\n")
            if blocked:
                f.write("### Blocked (please verify manually)\n\n| URL | Error |\n|---|---|\n")
                for b in blocked:
                    f.write(f"| {b['url']} | {b['error']} |\n")

    if blocked:
        print(f"::warning::{len(blocked)} link(s) returned bot-protection style responses; verify manually.")

    if broken:
        print(f"::error::{len(broken)} broken link(s) found in {args.file}")
        sys.exit(1)

    print("All links OK (some may be unverifiable due to bot protection; see summary).")
    sys.exit(0)


if __name__ == "__main__":
    main()
