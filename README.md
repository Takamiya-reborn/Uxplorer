# Uxplorer

一个基于 PySide6 的 Windows 文件浏览器，专注浏览 `C:\Users` 下的用户目录，并为每个目录标注**手动更改的风险等级**——高危、存疑、安全，帮助你判断哪些东西能动、哪些千万别碰。

## 功能特性

### 📁 目录浏览

- **范围锁定**：只能导航到 `C:\Users` 及其子目录，不会误入其他区域
- **面包屑路径栏**：点击任意层级快速跳转
- **导航历史**：支持后退 / 前进 / 上一级（`Alt+←` / `Alt+→` / `Alt+↑`）
- **隐藏项目开关**：一键显示 / 隐藏以 `.` 开头或带 Windows 隐藏属性的条目
- **快捷方式识别**：`.lnk` / `.url` 文件与符号链接、junction 按快捷方式展示，不参与文件夹导航

### ⚠️ 风险分析

浏览目录时，每个条目都会按行背景色标注风险等级，悬浮可查看判定原因：

| 等级 | 行背景色 | 含义                                                                     |
| ---- | -------- | ------------------------------------------------------------------------ |
| 高危 | 🔴 浅红  | 手动更改会导致系统无法正常运行（如 `NTUSER.DAT`、`AppData` 根目录）      |
| 存疑 | 🟡 浅黄  | 手动更改会导致某些应用失去记录或无法正常运行（如个人文件目录、应用配置） |
| 安全 | 🟢 浅绿  | 删除后应用仍可正常工作，内容会自动重建或重新下载（如 `Temp`、`node_modules`、`__pycache__`） |

除综合等级外，悬浮提示还区分**删除风险**与**修改风险**两个维度（如 `node_modules` 删除安全但内部文件不应手动改动），并给出具体操作建议与采样证据。"容器"类目录（如用户根目录）本身不可删除或重命名，但内部子项可独立管理。

具体规则存放在随包分发的 SQLite 规则库 `resources/rules.db` 中（由 `scripts/rules_seed.sql` 生成，可用 DB Browser 直接编辑），判定时由具体到抽象逐层匹配：

1. **静态规则**：按优先级依次检查规则库中的名称 / 前缀 / 正则规则，首个命中生效（注册表配置单元、AppData 前缀表、个人数据目录、OneDrive 同步目录、可重建的开发依赖等）
2. **内容采样**：扫描目录内文件的元数据（扩展名、注册表配置单元、目录所有者是否为 SYSTEM / TrustedInstaller），按缓存文件占比推断等级
3. **兜底**：无法确定内容时默认视为重要数据（存疑）；规则库缺失或损坏时同样全部保守回退为存疑

### 🤖 提示词生成

- 选中一个或多个条目，右键 **"生成提示词并复制"**：把路径、类型、大小、访问控制（所有者 / DACL）与本地风险分析结论拼装成一段可直接粘贴给大模型的提示词，请它逐个分析用途与删除 / 修改风险
- 纯本地拼装：不读取任何文件内容，也不调用外部模型
- 提示词会离开本机，因此路径、名称与规则理由中的真实用户名一律替换为 `<用户名>` 占位符

### 🔍 文件列表

- **四列视图**：名称 / 修改时间 / 类型 / 大小，列宽比例与 Windows 资源管理器一致，点击表头排序（文件夹固定在前）
- **自然排序**：`文件2` 排在 `文件10` 之前
- **类型分类**：按扩展名分为图片 / 视频 / 音频 / 压缩包 / 代码 / 文档 / 可执行文件等，以彩色圆点标识
- **即时搜索**：按名称子串过滤当前目录，300ms 防抖
- **右键菜单**：在资源管理器中打开（定位选中条目）、查看文件属性、生成提示词并复制（见下方"提示词生成"）；支持 `Ctrl` / `Shift` 多选
- **渐进加载**：列表分批渲染（每批 200 项），大目录不卡顿

### 🎨 界面

- Windows 11 风格的自绘表头与行卡片
- 深 / 浅色主题一键切换
- 空状态提示（"此文件夹为空" / "无匹配项"）与状态栏项目计数

## 环境要求

- Windows 10 / 11
- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/)

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/Takamiya-reborn/Uxplorer.git
cd Uxplorer

# 安装依赖并运行
uv sync
uv run uxplorer
```

或直接调用模块：

```bash
uv run python -m uxplorer
```

打包为可执行文件（[Nuitka](https://nuitka.net/)）：

```powershell
.\scripts\nuitka-onefile.ps1     # onefile 单文件
.\scripts\nuitka-standalone.ps1 # standalone 目录，启动更快
```

## 项目结构

```
src/uxplorer/
├── __init__.py            # 入口：创建 QApplication 并启动主窗口
├── __main__.py            # python -m uxplorer 与 Nuitka 打包的入口
├── core/                  # 纯逻辑层，不依赖 Qt
│   ├── api.py             # 目录枚举、导航范围校验、调起资源管理器 / 属性对话框
│   ├── file_logic.py      # FileEntry 数据模型、排序 / 过滤 / 分类 / 大小格式化
│   ├── risk_analysis.py   # 目录风险等级判定（规则库匹配 + 内容采样）
│   ├── rule_store.py      # SQLite 规则库加载与编译
│   ├── prompt_bot.py      # 提示词拼装（含用户名脱敏）
│   └── ...
├── resources/             # 静态资源（统一入口 resources/__init__.py）
│   ├── rules.db           # 规则库（由 scripts/rules_seed.sql 生成）
│   └── qss/               # 深色 / 浅色主题样式表
└── ui/                    # 界面层
    ├── main_window.py     # 主窗口：工具栏、面包屑、表头、列表组装与交互
    ├── models.py          # QAbstractListModel：排序 / 过滤 / 渐进加载 / 风险缓存
    ├── delegates.py       # 行卡片自绘：图标、列几何、风险背景与边框
    ├── theme.py           # 颜色、列宽计算、图标生成、主题切换
    └── ...

scripts/
├── build_rules_db.py      # 从 rules_seed.sql 重新生成 resources/rules.db
├── nuitka-onefile.ps1     # Nuitka 打包（onefile 单文件）
└── nuitka-standalone.ps1  # Nuitka 打包（standalone 目录）
```

分层约定：`core` 不 import Qt，可单独测试；`ui` 只通过 `core.api` 访问文件系统。

## 技术栈

- [PySide6](https://www.qt.io/product/qt-for-python) — GUI 框架
- [lucide](https://lucide.dev/) — SVG 图标
- [uv](https://docs.astral.sh/uv/) — 包管理与构建

## 已知限制

- 导航范围硬编码为 `C:\Users`（见 `core/api.py` 中的 `ROOT`），暂不支持其他盘符或自定义根目录
- Windows 专用：部分功能依赖 `explorer /select`、`SHObjectProperties`、NTFS 所有者查询等 Win32 能力

## License

MIT
