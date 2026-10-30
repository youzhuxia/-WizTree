#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WizTree CLI wrapper: scan a Windows drive/folder and rank the biggest files
and folders, with optional junk-file audit output.

Examples
--------
    python wiztree_scan.py --path "C:" --top 20
    python wiztree_scan.py --path "C:\\Users" --kind files --top 30
    python wiztree_scan.py --path "C:" --filter "*.mp4|*.mkv" --json out.json
    python wiztree_scan.py --path "D:" --admin 1 --top 15

Notes on the tricky parts (learned the hard way)
-----------------------------------------------
* WizTree is a GUI-subsystem binary. Capturing its stdio or calling wait()
  can hang or kill the parent process. We fire-and-poll the CSV instead.
* WizTree rejects forward-slash targets by silently returning an empty scan
  (root node only, zero files). Normalise everything to backslashes.
* WizTree is single-instance; a stale process swallows new arguments.
* The /export value must not contain spaces.
* The CSV is UTF-8 with BOM, line 1 is a banner (not the header), and the
  header is localised (Chinese / English / ...).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NAME_KEYS = ("文件名称", "file name", "filename", "name")


def find_exe() -> str:
    """Locate WizTree: --exe / $WIZTREE_PATH / common install dirs / PATH."""
    env = os.environ.get("WIZTREE_PATH")
    if env and os.path.isfile(env):
        return env

    candidates = [
        os.path.expandvars(r"%ProgramFiles%\WizTree\WizTree64.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\WizTree\WizTree64.exe"),
        os.path.expandvars(r"%ProgramFiles%\WizTree\WizTree.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\WizTree\WizTree.exe"),
        r"C:\Program Files\WizTree\WizTree64.exe",
        r"C:\Program Files (x86)\WizTree\WizTree.exe",
    ]
    for c in candidates:
        if c and "%" not in c and os.path.isfile(c):
            return c

    for name in ("WizTree64.exe", "WizTree.exe"):
        found = shutil.which(name)
        if found:
            return found

    raise SystemExit(
        "WizTree not found.\n"
        "  Install it from https://diskanalyzer.com/download\n"
        "  or point WIZTREE_PATH at the executable."
    )


def kill_stale() -> None:
    """WizTree is single-instance; a leftover process ignores new arguments."""
    for exe in ("WizTree64.exe", "WizTree.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", exe],
                           capture_output=True, check=False, timeout=10)
        except Exception:
            pass
    time.sleep(0.8)


def run_export(target: str, out_csv, *, exe: str | None = None, admin: int = 0,
               file_filter: str | None = None, exclude: str | None = None,
               sortby: int = 1, export_folders: bool = True,
               export_files: bool = True, kill: bool = True,
               timeout: int = 900) -> Path:
    exe = exe or find_exe()
    if kill:
        kill_stale()

    out_csv = Path(out_csv)
    if out_csv.exists():
        out_csv.unlink()

    target = str(target).replace("/", "\\")

    # /export breaks on paths containing spaces -> stage in a clean temp dir.
    staging = None
    if " " in str(out_csv):
        staging = Path(tempfile.mkdtemp(prefix="wiz_out_"))
        export_path = staging / "export.csv"
    else:
        export_path = out_csv

    args = [exe, target, f"/export={str(export_path).replace('/', chr(92))}",
            f"/admin={admin}", f"/sortby={sortby}"]
    if not export_folders:
        args.append("/exportfolders=0")
    if not export_files:
        args.append("/exportfiles=0")
    if file_filter:
        args.append(f"/filter={file_filter}")
    if exclude:
        args.append(f"/filterexclude={exclude}")

    subprocess.Popen(args, close_fds=True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if export_path.exists() and export_path.stat().st_size > 0:
            s1 = export_path.stat().st_size
            time.sleep(0.6)
            if export_path.stat().st_size == s1:
                if staging is not None:
                    shutil.copy2(export_path, out_csv)
                    shutil.rmtree(staging, ignore_errors=True)
                return out_csv
        time.sleep(0.4)

    if staging is not None:
        shutil.rmtree(staging, ignore_errors=True)
    raise SystemExit(f"Export timed out after {timeout}s for target: {target}")


def parse_csv(path) -> list[dict]:
    records: list[dict] = []
    header_seen = False
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip():
                continue
            name = row[0].strip().strip('"')
            low = name.lower()
            if not header_seen:
                if any(k in low for k in NAME_KEYS):
                    header_seen = True
                continue

            def num(i: int) -> int:
                if len(row) <= i:
                    return 0
                v = row[i].strip().lstrip("0") or "0"   # hard links carry a leading 0
                try:
                    return int(v)
                except ValueError:
                    return 0

            is_dir = name.endswith("\\") or name.endswith("/")
            records.append({
                "name": name.rstrip("\\/") if is_dir else name,
                "size": num(1),
                "allocated": num(2),
                "modified": row[3].strip() if len(row) > 3 else "",
                "is_dir": is_dir,
                "files": num(5),
                "folders": num(6),
            })
    return records


def human(n: float) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(f) < 1024 or unit == "TB":
            return f"{int(f)} B" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Scan a Windows drive/folder with WizTree and rank the biggest items.")
    ap.add_argument("--path", required=True, help='scan target, e.g. "C:" or "C:\\Users"')
    ap.add_argument("--top", type=int, default=20, help="rows per list (default 20)")
    ap.add_argument("--kind", choices=["all", "files", "folders"], default="all")
    ap.add_argument("--filter", default=None, help='only files matching, e.g. "*.mp4|*.mkv"')
    ap.add_argument("--exclude", default=None, help='exclude matching paths')
    ap.add_argument("--admin", type=int, choices=[0, 1], default=0,
                    help="1 = admin/MFT mode, much faster, triggers UAC")
    ap.add_argument("--sortby", type=int, default=1,
                    help="0 name, 1 size desc, 2 allocated desc, 3 modified desc")
    ap.add_argument("--json", default=None, help="also write results as JSON")
    ap.add_argument("--save-csv", default=None, help="keep the raw WizTree CSV here")
    ap.add_argument("--exe", default=None, help="explicit path to WizTree64.exe")
    ap.add_argument("--no-kill", action="store_true",
                    help="do not kill running WizTree instances first")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    exe = args.exe or find_exe()
    workdir = Path(tempfile.mkdtemp(prefix="wiztree_"))
    tmp_csv = workdir / "export.csv"

    try:
        run_export(args.path, tmp_csv, exe=exe, admin=args.admin,
                   file_filter=args.filter, exclude=args.exclude,
                   sortby=args.sortby, kill=not args.no_kill,
                   timeout=args.timeout)
        records = parse_csv(tmp_csv)
        if args.save_csv:
            shutil.copy2(tmp_csv, args.save_csv)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not records:
        print("No data returned. Check the path exists and you have read access.")
        return

    # The root row only exists on unfiltered scans; with --filter the first row
    # is already a file, so locate the root by path instead of by position.
    target_norm = str(args.path).replace("/", "\\").rstrip("\\").lower()
    root = next((r for r in records
                 if r["is_dir"] and r["name"].lower().rstrip("\\") == target_norm), None)
    entries = [r for r in records if r is not root] if root else records
    files = [e for e in entries if not e["is_dir"]]
    dirs = [e for e in entries if e["is_dir"]]
    total = sum(f["size"] for f in files)

    print(f"Target : {args.path}")
    if root:
        print(f"Total  : {human(root['size'])}  |  files {root['files']:,}  "
              f"|  folders {root['folders']:,}")
    else:
        print(f"Total  : {human(total)}  (filtered)")
    print(f"Entries: {len(files):,} files / {len(dirs):,} folders\n")

    if args.kind in ("all", "folders") and dirs:
        print(f"== Top {min(args.top, len(dirs))} folders ==")
        print("   (percent of all file bytes; folders nest, so these add up past 100%)")
        for i, d in enumerate(sorted(dirs, key=lambda x: -x["size"])[:args.top], 1):
            pct = (d["size"] / total * 100) if total else 0
            print(f"{i:>3}. {human(d['size']):>10}  {pct:>5.1f}%  {d['name']}")
        print()

    if args.kind in ("all", "files") and files:
        print(f"== Top {min(args.top, len(files))} files ==")
        for i, f in enumerate(sorted(files, key=lambda x: -x["size"])[:args.top], 1):
            pct = (f["size"] / total * 100) if total else 0
            print(f"{i:>3}. {human(f['size']):>10}  {pct:>5.1f}%  {f['name']}")

    if args.json:
        payload = {
            "target": args.path,
            "root": root,
            "total_file_bytes": total,
            "largest_folders": sorted(dirs, key=lambda x: -x["size"])[:args.top],
            "largest_files": sorted(files, key=lambda x: -x["size"])[:args.top],
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON written: {args.json}")


if __name__ == "__main__":
    main()
