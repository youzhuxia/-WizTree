---
name: wiztree
description: |
  用 WizTree 命令行扫描 Windows 磁盘/目录，找出最占空间的文件和文件夹，支持按扩展名过滤、导出 CSV、生成 JSON。
  触发词：WizTree、磁盘空间、C盘满了、清理磁盘、找出大文件、哪个文件夹最占空间、空间分析、磁盘分析、du、磁盘占用、清理空间、腾出空间、大文件排行。
description_en: |
  Scan Windows disks or folders with the WizTree CLI to find the largest files and folders.
  Supports extension filters, CSV export, and JSON output. Use for disk space analysis,
  finding large files, and cleanup planning.
---

# WizTree 磁盘空间分析

WizTree 直接读 NTFS 的 MFT 表，扫全盘通常只要几秒到几十秒，比 `du` / WinDirStat 快一个数量级。**它只做分析，不删任何东西**——这一点必须先跟用户讲清楚。

## 环境

- WizTree（免费版够用）：https://diskanalyzer.com/download
- 默认安装路径 `C:\Program Files\WizTree\WizTree64.exe`；装在别处就用 `--exe` 或环境变量 `WIZTREE_PATH` 指定
- Python 3.9+（用了 `X | None` 语法）

## 首选：用封装脚本

```bash
# 全盘，看最大目录和文件
python3 scripts/wiztree_scan.py --path "C:" --top 20

# 只看大文件，按扩展名过滤
python3 scripts/wiztree_scan.py --path "C:" --kind files --filter "*.mp4|*.mkv|*.iso" --top 30

# 管理员模式（读 MFT，最快），会弹一次 UAC
python3 scripts/wiztree_scan.py --path "D:" --admin 1 --top 15

# 存 JSON 供后续加工，同时保留原始 CSV
python3 scripts/wiztree_scan.py --path "C:\\Users" --json scan.json --save-csv raw.csv
```

脚本已经处理好编码、单实例、临时文件、CSV 解析，输出带百分比的可读榜单。

## 备选：直接调 WizTree CLI

只有在脚本不够用时才手写命令。**必须用 PowerShell 或原生 subprocess，不要在 Git Bash 里拼参数。**

```powershell
& "C:\Program Files\WizTree\WizTree64.exe" "C:" /export="C:\temp\out.csv" /admin=1 /sortby=1
```

### 参数速查

| 参数 | 说明 |
|---|---|
| `"C:"` 或 `"C:\Windows"` | 扫描目标，作为第一个位置参数 |
| `/export="file.csv"` | 导出 CSV。`%d`=日期 `%t`=时间 |
| `/filter="*.mp3\|*.wav"` | 仅导出匹配文件，`\|` 分隔多模式 |
| `/filterexclude="C:\Temp\"` | 排除 |
| `/admin=1` | 管理员模式，读 MFT，最快；会弹 UAC |
| `/exportfolders=0` | 不导出目录 |
| `/exportfiles=0` | 不导出文件 |
| `/sortby=` | 0 名称 / 1 大小降序 / 2 分配大小降序 / 3 修改时间降序 |
| `/exportfiletypes="f.csv"` | 按扩展名汇总导出另一张表 |
| `/exportmaxdepth=n` | 限制目录深度 |
| `/exportalldates=1` | 附带创建/访问时间 |
| `/treemapimagefile="x.png"` | 导出矩形树图 PNG（可配 `width`/`height`） |

### CSV 列结构

```
文件名称, 大小, 分配, 修改时间, 属性, 文件, 文件夹, DRIVECAPACITY, FREESPACE, USEDSPACE, RESERVEDSPACE
```

- 首行是 WizTree 版权信息，**不是表头**，解析时要跳过
- 文件是 UTF-8 **带 BOM**，用 `utf-8-sig` 读
- 表头随系统语言变化（中文 / 英文 / …），按关键字匹配列，不要写死下标
- **目录名结尾带 `\`**，以此区分文件和目录
- `大小` 对目录表示递归总量；`文件`/`文件夹` 列只对目录有意义
- `分配` 列**前导 0 表示硬链接**（不额外占空间），统计总量时要去掉前导 0 且不应计入
- **统计汇总时只能累加文件记录**。目录记录已经是递归值，再加一遍会翻好几倍

## 三个必须避开的坑

1. **路径斜杠**。WizTree 拿到含正斜杠的目标（`C:/Program Files/X`）会扫出空结果——只有一个根节点、文件数 0。而 Git Bash / MSYS2 会主动把 `C:\...` 改写成 `C:/...`。封装脚本已做归一化，但**直接用 CLI 时必须传纯反斜杠路径**，或者干脆走 PowerShell。
2. **单实例 + 管道**。WizTree 是 GUI 子系统程序：已有进程在跑时新参数可能被吞掉；`subprocess.run(capture_output=True)` 或给 stdin/stdout 挂 DEVNULL 会让父进程被卡死/杀掉。正确姿势是 `Popen` 后 fire-and-poll，轮询 CSV 是否生成、大小是否稳定。
3. **导出路径别带空格**。`/export="C:\a b\x.csv"` 容易被引号解析搞坏，先写无空格临时目录再搬。

## 实测基准

WizTree 4.33，非管理员模式，NVMe 硬盘：

- 150 GB / 1,488,576 个文件 / 171,984 个目录 → **35 秒**
- 全盘 C:（295 GB / 190 万文件）→ **32 秒**
- 单个程序目录（68 文件）→ 1～2 秒

全盘用 `/admin=1` 走 MFT 会更快，但会弹一次 UAC。

## 输出口径说明

百分比是「占全部文件总量」的比例。目录之间存在嵌套（`AppData` 包含 `AppData\Local`），所以目录榜单的比例相加会超过 100%，这是正常的，不是算错。

## 结果怎么用

- 报给用户时按「大小 + 占总量百分比 + 完整路径」给榜单，别只给数字
- 想清理时**先出报告，不要直接动手**。列出候选路径、大小、风险等级，让用户勾选
- 用户目录（Desktop / Downloads / Documents）属于个人文件区，任何删除动作都要先备份、走回收站、分批执行、逐批确认
- 判断"垃圾"要看路径语义：`C:\Windows\Installer`、`C:\Windows\WinSxS` 看着大但**不能删**；`%TEMP%`、`C:\$Recycle.Bin`、浏览器缓存才是安全目标
- 休眠文件 `hiberfil.sys`、页面文件 `pagefile.sys` 是系统占用，要通过系统设置调整而非删除
- `WinSxS` 只能 `DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase`
