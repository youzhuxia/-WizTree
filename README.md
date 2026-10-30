# wiztree-skill

> Agent skill for [WizTree](https://diskanalyzer.com/) — scan Windows disks from the CLI, rank the largest files and folders, and audit junk files by risk level.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue)

WizTree reads the NTFS MFT directly, so a full-disk scan takes seconds instead of minutes. This skill wraps its command line into a clean, scriptable interface that an AI agent (or you) can call to answer questions like *"what's eating my C: drive?"*

It **never deletes anything**. It only scans and reports.

---

## Why this exists

WizTree's CLI works, but wiring it up is full of traps that silently produce empty results:

- Pass a forward-slash path (`C:/Program Files/X`) and you get a scan with **zero files** — no error, just an empty root node.
- Capture its stdout (`subprocess.run(..., capture_output=True)`) and your parent process gets killed. It's a GUI-subsystem binary.
- Run it while another instance is alive and your new arguments are **silently swallowed** — WizTree is single-instance.
- The exported CSV is UTF-8 **with BOM**, its first line is a banner rather than the header, and the header is **localised**.
- Folder rows carry *recursive* sizes, so naively summing every row inflates totals several-fold.

This repo encodes all of that so you don't rediscover it.

---

## Requirements

| | |
|---|---|
| OS | Windows (WizTree is Windows-only) |
| Python | 3.9+ |
| WizTree | Free version is enough — [download](https://diskanalyzer.com/download) |

## Install

```bash
git clone https://github.com/<you>/wiztree-skill.git
cd wiztree-skill
```

No dependencies — standard library only.

If WizTree lives somewhere non-standard, either pass `--exe` or set an env var:

```bash
export WIZTREE_PATH="D:\Tools\WizTree\WizTree64.exe"
```

## Usage

```bash
# Full disk, top 20 folders and files
python scripts/wiztree_scan.py --path "C:" --top 20

# Only files, filtered by extension
python scripts/wiztree_scan.py --path "C:" --kind files --filter "*.mp4|*.mkv|*.iso" --top 30

# Admin / MFT mode — fastest, triggers one UAC prompt
python scripts/wiztree_scan.py --path "D:" --admin 1 --top 15

# Machine-readable output
python scripts/wiztree_scan.py --path "C:\\Users" --json scan.json --save-csv raw.csv
```

### Sample output

```
Target : C:\Program Files\WizTree
Total  : 20.2 MB  |  files 68  |  folders 61
Entries: 68 files / 61 folders

== Top 5 folders ==
  1.     1.4 MB    7.0%  C:\Program Files\WizTree\locale
  2.    67.6 KB    0.3%  C:\Program Files\WizTree\locale\th
  3.    67.6 KB    0.3%  C:\Program Files\WizTree\locale\th\LC_MESSAGES
  4.    60.4 KB    0.3%  C:\Program Files\WizTree\locale\el
  5.    60.4 KB    0.3%  C:\Program Files\WizTree\locale\el\LC_MESSAGES

== Top 5 files ==
  1.    10.5 MB   52.1%  C:\Program Files\WizTree\WizTree64.exe
  2.     7.1 MB   35.0%  C:\Program Files\WizTree\WizTree.exe
  3.     1.1 MB    5.6%  C:\Program Files\WizTree\unins000.exe
  4.    36.2 KB    0.2%  C:\Program Files\WizTree\locale\th\LC_MESSAGES\default.po
  5.    35.1 KB    0.2%  C:\Program Files\WizTree\unins000.dat
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--path` | *required* | Scan target, e.g. `"C:"` or `"C:\Users"` |
| `--top` | `20` | Rows per list |
| `--kind` | `all` | `all` / `files` / `folders` |
| `--filter` | – | Only files matching, e.g. `"*.mp4\|*.mkv"` |
| `--exclude` | – | Exclude matching paths |
| `--admin` | `0` | `1` = MFT mode (fast, UAC prompt) |
| `--sortby` | `1` | `0` name, `1` size, `2` allocated, `3` modified |
| `--json` | – | Write results as JSON |
| `--save-csv` | – | Keep the raw WizTree CSV |
| `--exe` | auto | Explicit path to `WizTree64.exe` |
| `--no-kill` | off | Don't kill running WizTree instances first |
| `--timeout` | `900` | Seconds to wait for the export |

## Raw WizTree CLI

Useful when the wrapper isn't enough. **Run it from PowerShell or a native subprocess — not Git Bash.**

```powershell
& "C:\Program Files\WizTree\WizTree64.exe" "C:" /export="C:\temp\out.csv" /admin=1 /sortby=1
```

| Parameter | Description |
|---|---|
| `"C:"` / `"C:\Windows"` | Scan target (first positional arg) |
| `/export="file.csv"` | Export CSV. `%d` = date, `%t` = time |
| `/filter="*.mp3\|*.wav"` | Only matching files |
| `/filterexclude="C:\Temp\"` | Exclude |
| `/admin=1` | Admin / MFT mode |
| `/exportfolders=0` | Skip folders |
| `/exportfiles=0` | Skip files |
| `/sortby=` | `0` name, `1` size, `2` allocated, `3` modified |
| `/exportfiletypes="f.csv"` | Second CSV grouped by extension |
| `/exportmaxdepth=n` | Limit folder depth |
| `/treemapimagefile="x.png"` | Export a treemap PNG |

### CSV layout

```
File Name, Size, Allocated, Modified, Attributes, Files, Folders, DRIVECAPACITY, FREESPACE, USEDSPACE, RESERVEDSPACE
```

- Line 1 is a banner, **not** the header
- UTF-8 **with BOM** → read as `utf-8-sig`
- Header is localised; match by keyword, not by index
- **Folders end with `\`**
- `Size` on a folder is recursive
- A leading `0` in `Allocated` marks a **hard link** (occupies no extra space)
- When aggregating, **only sum file rows** — folder rows are already recursive

## Benchmarks

WizTree 4.33, non-admin, NVMe:

| Target | Data | Time |
|---|---|---|
| User profile | 150 GB / 1.49M files / 172K folders | **35 s** |
| Full C: | 295 GB / 1.9M files | **32 s** |
| Program folder | 68 files | 1–2 s |

## Using it as an agent skill

Copy `SKILL.md` and `scripts/` into your agent's skills directory. The `description` frontmatter contains the trigger phrases the agent uses to decide when to invoke it.

For WorkBuddy: `~/.workbuddy-ai/skills/wiztree/`

## Safety notes

This tool is read-only, but the **cleanup decisions** it informs are not. A few rules worth keeping:

- `C:\Windows\WinSxS` — never delete. Only `DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase`.
- `C:\Windows\Installer` — never delete. Uninstall/repair breaks without it.
- `pagefile.sys` / `hiberfil.sys` — change via system settings, not deletion.
- Personal folders (Desktop, Downloads, Documents) — back up, use the Recycle Bin, small batches.

## License

MIT — see [LICENSE](LICENSE).

---

## 中文说明

**一句话**：把 WizTree 的命令行封装成一个能直接调用的脚本，秒扫 Windows 全盘，输出最大文件/目录榜单。

```bash
git clone https://github.com/<you>/wiztree-skill.git
cd wiztree-skill

python scripts/wiztree_scan.py --path "C:" --top 20
```

**为什么需要它**：WizTree 的 CLI 有几个静默失败的坑——正斜杠路径会扫出空结果、捕获输出会导致父进程被杀、单实例会吞掉新参数、CSV 带 BOM 且表头随系统语言变化、目录行是递归值不能重复累加。这些都在脚本里处理好了。

**实测**：150 GB / 149 万文件，35 秒扫完。

详细参数和避坑说明见 [SKILL.md](SKILL.md)。
