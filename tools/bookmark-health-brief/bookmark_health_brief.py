#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

WINDOWS_EPOCH_OFFSET = 11644473600


@dataclass
class BookmarkEntry:
    title: str
    url: str
    folder_path: str
    depth: int
    added_at: str | None


@dataclass
class FolderEntry:
    path: str
    depth: int
    children: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Chrome or Edge bookmark exports for duplicates, risky URLs, and cleanup hotspots."
    )
    parser.add_argument("--input", type=Path, required=True, help="Bookmark export JSON file.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON report path.")
    parser.add_argument("--markdown-out", type=Path, help="Optional Markdown report path.")
    parser.add_argument("--check-urls", action="store_true", help="Check HTTP/HTTPS URLs for reachability.")
    parser.add_argument("--timeout", type=float, default=4.0, help="Per-request timeout when --check-urls is used.")
    parser.add_argument("--deep-folder-threshold", type=int, default=5, help="Folder depth that starts counting as overly deep.")
    parser.add_argument("--report-limit", type=int, default=10, help="Maximum rows per printed section.")
    return parser.parse_args()


def chrome_timestamp_to_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        seconds = int(raw) / 1_000_000 - WINDOWS_EPOCH_OFFSET
    except ValueError:
        return None
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_export(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def walk_nodes(node: dict[str, object], trail: list[str], bookmarks: list[BookmarkEntry], folders: list[FolderEntry]) -> None:
    node_type = str(node.get("type", ""))
    title = str(node.get("name", "")).strip() or "(untitled)"
    current_trail = trail + [title]
    depth = max(0, len(current_trail) - 1)

    if node_type == "folder":
      children = node.get("children", [])
      if isinstance(children, list):
          folders.append(FolderEntry(path=" / ".join(current_trail), depth=depth, children=len(children)))
          for child in children:
              if isinstance(child, dict):
                  walk_nodes(child, current_trail, bookmarks, folders)
      return

    url = str(node.get("url", "")).strip()
    if not url:
        return
    bookmarks.append(
        BookmarkEntry(
            title=title,
            url=url,
            folder_path=" / ".join(trail) if trail else "(root)",
            depth=depth,
            added_at=chrome_timestamp_to_iso(node.get("date_added")),
        )
    )


def extract_entries(export: dict[str, object]) -> tuple[list[BookmarkEntry], list[FolderEntry]]:
    roots = export.get("roots")
    if not isinstance(roots, dict):
        raise ValueError("Expected a Chrome/Edge-style bookmark export with a roots object.")

    bookmarks: list[BookmarkEntry] = []
    folders: list[FolderEntry] = []
    for root_name in ("bookmark_bar", "other", "synced"):
        root = roots.get(root_name)
        if isinstance(root, dict):
            walk_nodes(root, [str(root.get("name", root_name)).strip() or root_name], bookmarks, folders)
    if not bookmarks:
        raise ValueError("No bookmark URLs found in the export.")
    return bookmarks, folders


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def classify_url(url: str) -> str:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme == "http":
        return "http"
    if scheme == "file":
        return "file"
    if scheme == "javascript":
        return "javascript"
    if scheme in {"chrome", "edge", "about"}:
        return "browser-internal"
    return "standard"


def check_url(url: str, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "bookmark-health-brief/1.0"},
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"url": url, "ok": True, "status": getattr(response, "status", 200)}
    except urllib.error.HTTPError as error:
        if error.code in {405, 403}:
            get_request = urllib.request.Request(url, headers={"User-Agent": "bookmark-health-brief/1.0"})
            try:
                with urllib.request.urlopen(get_request, timeout=timeout) as response:
                    return {"url": url, "ok": True, "status": getattr(response, "status", 200)}
            except Exception as nested_error:  # noqa: BLE001
                return {"url": url, "ok": False, "error": str(nested_error)}
        return {"url": url, "ok": False, "status": error.code, "error": error.reason}
    except (urllib.error.URLError, socket.timeout, ValueError) as error:
        return {"url": url, "ok": False, "error": str(error)}


def build_report(
    export_path: Path,
    *,
    deep_folder_threshold: int,
    check_urls: bool,
    timeout: float,
) -> dict[str, object]:
    export = load_export(export_path)
    bookmarks, folders = extract_entries(export)

    duplicate_urls: dict[str, list[dict[str, str]]] = defaultdict(list)
    duplicate_titles: dict[str, list[dict[str, str]]] = defaultdict(list)
    folder_counts = Counter(entry.folder_path for entry in bookmarks)
    risky_urls: list[dict[str, str]] = []

    for entry in bookmarks:
        normalized_url = normalize_url(entry.url)
        duplicate_urls[normalized_url].append({"title": entry.title, "folder_path": entry.folder_path})
        duplicate_titles[entry.title.lower()].append({"title": entry.title, "url": entry.url, "folder_path": entry.folder_path})
        url_kind = classify_url(entry.url)
        if url_kind != "standard":
            risky_urls.append({"title": entry.title, "url": entry.url, "kind": url_kind, "folder_path": entry.folder_path})

    url_duplicates = [
        {"url": url, "count": len(rows), "entries": rows}
        for url, rows in duplicate_urls.items()
        if len(rows) > 1
    ]
    title_duplicates = [
        {"title": rows[0]["title"], "count": len(rows), "entries": rows}
        for rows in duplicate_titles.values()
        if len(rows) > 1
    ]
    empty_folders = [asdict(folder) for folder in folders if folder.children == 0]
    deep_folders = [asdict(folder) for folder in folders if folder.depth >= deep_folder_threshold]
    top_folders = sorted(folder_counts.items(), key=lambda item: (-item[1], item[0]))[:8]

    url_checks = []
    if check_urls:
        seen_urls: set[str] = set()
        candidates = []
        for entry in bookmarks:
            normalized = normalize_url(entry.url)
            if normalized in seen_urls:
                continue
            if urllib.parse.urlsplit(entry.url).scheme.lower() not in {"http", "https"}:
                continue
            seen_urls.add(normalized)
            candidates.append(entry.url)
        url_checks = [check_url(url, timeout) for url in candidates]

    return {
        "input": str(export_path.resolve()),
        "bookmark_count": len(bookmarks),
        "folder_count": len(folders),
        "duplicate_url_groups": sorted(url_duplicates, key=lambda row: (-row["count"], row["url"])),
        "duplicate_title_groups": sorted(title_duplicates, key=lambda row: (-row["count"], row["title"].lower())),
        "risky_urls": risky_urls,
        "empty_folders": empty_folders,
        "deep_folders": sorted(deep_folders, key=lambda row: (-row["depth"], row["path"])),
        "top_folders": top_folders,
        "url_checks": [row for row in url_checks if not row.get("ok")],
        "checked_urls": check_urls,
    }


def render_markdown(report: dict[str, object], report_limit: int) -> str:
    lines = [
        "# Bookmark Health Brief",
        "",
        f"- Input: `{report['input']}`",
        f"- Bookmarks: `{report['bookmark_count']}`",
        f"- Folders: `{report['folder_count']}`",
        f"- Duplicate URL groups: `{len(report['duplicate_url_groups'])}`",
        f"- Duplicate title groups: `{len(report['duplicate_title_groups'])}`",
        f"- Risky URLs: `{len(report['risky_urls'])}`",
        f"- Empty folders: `{len(report['empty_folders'])}`",
        f"- Deep folders: `{len(report['deep_folders'])}`",
        "",
        "## Cleanup Hotspots",
        "",
    ]

    top_folders = report["top_folders"]
    if top_folders:
        for folder_path, count in top_folders:
            lines.append(f"- `{folder_path}`: {count} bookmark(s)")
    else:
        lines.append("- None.")

    def add_group_section(title: str, rows: list[dict[str, object]], formatter) -> None:
        lines.extend(["", f"## {title}", ""])
        if not rows:
            lines.append("- None.")
            return
        for row in rows[:report_limit]:
            lines.append(formatter(row))

    add_group_section(
        "Duplicate URLs",
        report["duplicate_url_groups"],
        lambda row: f"- `{row['url']}` appears {row['count']} times",
    )
    add_group_section(
        "Duplicate Titles",
        report["duplicate_title_groups"],
        lambda row: f"- `{row['title']}` appears {row['count']} times",
    )
    add_group_section(
        "Risky URLs",
        report["risky_urls"],
        lambda row: f"- `{row['title']}` -> `{row['url']}` ({row['kind']}) in `{row['folder_path']}`",
    )
    add_group_section(
        "Empty Folders",
        report["empty_folders"],
        lambda row: f"- `{row['path']}`",
    )
    add_group_section(
        "Deep Folders",
        report["deep_folders"],
        lambda row: f"- `{row['path']}` depth {row['depth']}",
    )
    add_group_section(
        "Failed URL Checks",
        report["url_checks"],
        lambda row: f"- `{row['url']}`: {row.get('status', row.get('error', 'failed'))}",
    )
    return "\n".join(lines)


def print_report(report: dict[str, object], report_limit: int) -> None:
    print("Bookmark Health Brief")
    print("=====================")
    print(f"Input:                 {report['input']}")
    print(f"Bookmarks:             {report['bookmark_count']}")
    print(f"Folders:               {report['folder_count']}")
    print(f"Duplicate URL groups:  {len(report['duplicate_url_groups'])}")
    print(f"Duplicate title sets:  {len(report['duplicate_title_groups'])}")
    print(f"Risky URLs:            {len(report['risky_urls'])}")
    print(f"Empty folders:         {len(report['empty_folders'])}")
    print(f"Deep folders:          {len(report['deep_folders'])}")
    if report["checked_urls"]:
        print(f"Failed URL checks:     {len(report['url_checks'])}")

    if report["duplicate_url_groups"]:
        print("\nTop duplicate URLs:")
        for row in report["duplicate_url_groups"][:report_limit]:
            print(f"  {row['url']} ({row['count']} copies)")

    if report["risky_urls"]:
        print("\nRisky URLs:")
        for row in report["risky_urls"][:report_limit]:
            print(f"  {row['title']} -> {row['url']} ({row['kind']})")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    report = build_report(
        args.input,
        deep_folder_threshold=max(1, args.deep_folder_threshold),
        check_urls=args.check_urls,
        timeout=max(0.5, args.timeout),
    )
    print_report(report, report_limit=max(1, args.report_limit))

    if args.json_out:
        write_text(args.json_out, json.dumps(report, indent=2))
        print(f"\nWrote JSON report: {args.json_out}")

    if args.markdown_out:
        write_text(args.markdown_out, render_markdown(report, report_limit=max(1, args.report_limit)))
        print(f"Wrote Markdown report: {args.markdown_out}")


if __name__ == "__main__":
    main()
