#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Personal-NonCommercial
# Copyright (c) 2026 Alexander Kurach. See ../LICENSE.
"""Public MOEX ISS GET client. Python 3.9+, standard library only."""

import argparse
import hashlib
import json
import re
import ssl
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def table_rows(table):
    if not isinstance(table, dict):
        raise ValueError("Expected a compact ISS table")
    columns, data = table.get("columns"), table.get("data")
    if not isinstance(columns, list) or not isinstance(data, list):
        raise ValueError("Expected columns and data; extended JSON is unsupported")
    if not all(isinstance(c, str) for c in columns) or len(set(columns)) != len(columns):
        raise ValueError("Invalid or duplicate column names")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in data):
        raise ValueError("Row width differs from columns")
    return [dict(zip(columns, row)) for row in data]


def retry_delay(value):
    if not value:
        return 1.0
    try:
        delay = float(value)
    except ValueError:
        delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
    if delay > 30:
        raise ValueError(f"Server requested Retry-After={value}; retry later")
    return max(0.0, delay)


def fetch(url, timeout):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "moex-iss-data/1.0"})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
                source = {
                    "url": url,
                    "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                    "http_status": response.status,
                    "passport_marker": response.headers.get("X-MicexPassport-Marker"),
                }
            if not isinstance(payload, dict):
                raise ValueError("Expected compact JSON object")
            return payload, source
        except HTTPError as error:
            error.close()
            if attempt == 0 and (error.code == 429 or 500 <= error.code <= 504):
                time.sleep(retry_delay(error.headers.get("Retry-After")))
                continue
            raise ValueError(f"HTTP {error.code}: {url}") from error
        except (URLError, TimeoutError) as error:
            if isinstance(getattr(error, "reason", error), ssl.SSLError):
                raise ValueError(f"TLS failure: {error}") from error
            if attempt == 0:
                time.sleep(1)
                continue
            raise ValueError(f"Transport failure after two attempts: {error}") from error


def collect(path, params, block=None, all_pages=False, max_pages=100, timeout=20, fetcher=fetch):
    if not re.fullmatch(r"/iss/[A-Za-z0-9_./%-]+\.json", path) or ".." in path:
        raise ValueError("Use an /iss/...json path without a host or query; use --param for query values")
    if max_pages < 1 or timeout <= 0:
        raise ValueError("max-pages and timeout must be positive")
    params = dict(params)
    if params.get("iss.json") not in (None, "compact"):
        raise ValueError("Only default/compact JSON is supported")
    if params.get("iss.data") == "off":
        raise ValueError("iss.data=off cannot be normalized as table data")
    if all_pages and (not block or block.endswith(".cursor")):
        raise ValueError("--all requires a data --block, not a cursor")
    if all_pages and any(key.endswith(".start") or key.endswith(".limit") for key in params):
        raise ValueError("Use unscoped start/limit so data and cursor stay aligned")
    start = int(params.get("start", 0))
    if start < 0:
        raise ValueError("start must be nonnegative")
    if all_pages:
        params["iss.only"] = f"{block},{block}.cursor"
    result = {
        "blocks": {}, "metadata": {}, "sources": [],
        "paging": {"requested": all_pages, "complete": None, "reason": "single_response", "start": start},
    }
    seen = set()
    previous_total = None
    for page in range(max_pages if all_pages else 1):
        if all_pages:
            params["start"] = start
        url = "https://iss.moex.com" + path + ("?" + urlencode(params) if params else "")
        payload, source = fetcher(url, timeout)
        result["sources"].append(source)
        names = [block] if block else list(payload)
        for name in names:
            if name not in payload:
                raise ValueError(f"Missing expected block {name}: {url}")
            rows = table_rows(payload[name])
            result["blocks"].setdefault(name, []).extend(rows)
            if "metadata" in payload[name]:
                result["metadata"][name] = payload[name]["metadata"]
        if not all_pages:
            return result
        rows = table_rows(payload[block])
        cursor_name = block + ".cursor"
        total = None
        if cursor_name in payload:
            cursor = table_rows(payload[cursor_name])
            if len(cursor) != 1:
                raise ValueError("Expected exactly one cursor row")
            index, total = int(cursor[0]["INDEX"]), int(cursor[0]["TOTAL"])
            if index != start or total < 0 or (rows and start + len(rows) > total):
                raise ValueError("Cursor does not match returned page")
            if previous_total is not None and previous_total != total:
                raise ValueError("Cursor TOTAL changed during pagination; split or retry a stable range")
            previous_total = total
        if not rows:
            if total is not None and start < total:
                raise ValueError("Empty page before cursor TOTAL; incomplete result")
            result["paging"].update(complete=True, reason="empty_page", next_start=start)
            return result
        fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        if fingerprint in seen:
            raise ValueError("Repeated page; endpoint may be ignoring start")
        seen.add(fingerprint)
        start += len(rows)
        if total is not None and start >= total:
            result["paging"].update(complete=True, reason="cursor_total", next_start=start, total=total)
            return result
        if page + 1 < max_pages:
            time.sleep(0.1)
    result["paging"].update(complete=False, reason="max_pages", next_start=start)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="/iss/...json; query values go in --param")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--block", help="Return only this table")
    parser.add_argument("--all", action="store_true", dest="all_pages", help="Paginate selected block")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    try:
        params = {}
        for item in args.param:
            key, separator, value = item.partition("=")
            if not separator or not key or key in params:
                raise ValueError(f"Invalid or duplicate parameter: {item}")
            params[key] = value
        result = collect(args.path, params, args.block, args.all_pages, args.max_pages, args.timeout)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
        sys.stdout.write("\n")
        return 3 if result["paging"]["complete"] is False else 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
