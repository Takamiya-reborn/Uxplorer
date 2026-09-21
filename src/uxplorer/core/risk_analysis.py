"""分析 C:\\Users 下目录的重要程度，评估手动更改的风险等级。

等级定义：
- 高危：手动更改会导致系统无法正常运行；
- 存疑：手动更改会导致某些应用失去记录或者无法正常运行；
- 安全：是缓存文件，不会导致数据丢失，也不会导致错误。
"""

from __future__ import annotations

import os
import stat as stat_mod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .api import ROOT, is_within_root

__all__ = ["RiskLevel", "RiskReport", "analyze_risk"]


class RiskLevel(Enum):
    """目录风险等级。"""

    HIGH = "high"  # 高危
    QUESTIONABLE = "caution"  # 存疑
    SAFE = "safe"  # 安全

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    RiskLevel.HIGH: "高危",
    RiskLevel.QUESTIONABLE: "存疑",
    RiskLevel.SAFE: "安全",
}


@dataclass(frozen=True)
class RiskReport:
    """风险分析结果。"""

    path: Path
    level: RiskLevel
    reason: str
    rule: str


# 个人数据目录（相对用户根目录的第一段），误删会造成数据丢失
_USER_DATA_DIRS = frozenset(
    {
        "desktop",
        "documents",
        "downloads",
        "pictures",
        "music",
        "videos",
        "favorites",
        "contacts",
        "links",
        "saved games",
        "searches",
        "3d objects",
    }
)

# 强缓存特征名称：在任何位置出现都视为缓存，可清理
_STRONG_CACHE_NAMES = frozenset(
    {
        "temp",
        "tmp",
        "crashpad",
        ".temp",
        ".tmp",
    }
)

# 可整体删除后由工具链重建的开发环境依赖目录：
# “删除安全”不等于“修改安全”，内部文件不应手动改动
_REBUILDABLE_CACHE_NAMES = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        "pnpm-store",
    }
)

# AppData 规则表，按最长前缀匹配
_APPDATA_RULES: tuple[tuple[tuple[str, ...], RiskLevel, str], ...] = (
    (
        ("appdata", "local", "microsoft", "windows"),
        RiskLevel.HIGH,
        "包含 UsrClass.dat 注册表配置单元等系统关键数据",
    ),
    (
        ("appdata", "local", "microsoft"),
        RiskLevel.QUESTIONABLE,
        "微软组件的用户数据与配置",
    ),
    (
        ("appdata", "local", "packages"),
        RiskLevel.QUESTIONABLE,
        "UWP 应用沙盒数据，误删会导致应用重置或需要重新登录",
    ),
    (("appdata", "local"), RiskLevel.QUESTIONABLE, "应用本地数据与配置"),
    (("appdata", "roaming"), RiskLevel.QUESTIONABLE, "应用漫游数据与配置"),
    (("appdata", "locallow"), RiskLevel.QUESTIONABLE, "应用低完整性级别数据"),
    (("appdata",), RiskLevel.HIGH, "AppData 根目录，删除会同时破坏系统组件与应用数据"),
)

# 采样时使用的扩展名特征
_HIVE_NAMES = ("ntuser.dat", "usrclass.dat")
_CACHE_EXTS = frozenset({"tmp", "temp", "log", "bak", "old", "dmp"})
_CONFIG_EXTS = frozenset({"json", "ini", "cfg", "conf", "db", "dat", "xml", "sqlite"})
# 重要配置扩展名：出现即可一票否决“安全”判定。
# 不含 .db/.sqlite——SQLite 库常与 .log 形式的 WAL 日志混放，
# 这类混合目录交给缓存比例判定处理
_VETO_CONFIG_EXTS = frozenset({"json", "ini", "dat"})
# 系统自动生成的杂项文件，不参与内容与同级判定
_IGNORED_FILE_NAMES = frozenset({"desktop.ini", "thumbs.db"})
# 缓存目录的同级配置文件特征：命中则缓存可能保存了应用状态
_SIBLING_CONFIG_EXTS = frozenset({"json", "ini"})
# 视为系统组件的目录所有者账户名
_SYSTEM_OWNER_ACCOUNTS = frozenset({"system", "trustedinstaller"})

_SAMPLE_LIMIT = 512


def analyze_risk(path: str | Path) -> RiskReport:
    """分析目录的手动更改风险。

    path 必须是 C:\\Users 下的子目录，否则抛出 PermissionError。
    """
    raw = Path(path)
    try:
        target = raw.resolve()
    except OSError:
        target = raw
    if not is_within_root(target) or target == ROOT:
        # 字面路径在范围内、解析后越界的是指向范围外的系统链接（如 All Users）
        if _is_lexically_within_root(raw):
            return RiskReport(
                raw,
                RiskLevel.QUESTIONABLE,
                f"系统链接，指向分析范围外的 {target}",
                "system-link",
            )
        raise PermissionError(f"路径超出分析范围: {target}")

    # 指向范围内的系统链接（如 Default User）同样按链接本身标注，不跟进目标
    if _is_reparse_point(raw):
        return RiskReport(
            target,
            RiskLevel.QUESTIONABLE,
            f"系统链接，指向 {target}",
            "system-link",
        )

    # 第一段是用户名，其余是相对用户根目录的路径
    under_user = tuple(part.lower() for part in target.relative_to(ROOT).parts[1:])

    if not under_user:
        return RiskReport(
            target,
            RiskLevel.HIGH,
            "用户配置文件根目录，包含注册表配置单元和系统必需数据",
            "profile-root",
        )

    first = under_user[0]
    last = under_user[-1]

    # OneDrive 同步目录（精确的 OneDrive，或 "OneDrive - 公司" 形式的变体；
    # 不匹配用户自建的 OneDriveBackup 之类文件夹）
    if first == "onedrive" or first.startswith("onedrive -"):
        return RiskReport(
            target,
            RiskLevel.QUESTIONABLE,
            "OneDrive 同步的个人文件，误删会造成数据丢失",
            "onedrive",
        )

    # 个人数据目录
    if first in _USER_DATA_DIRS:
        return RiskReport(
            target,
            RiskLevel.QUESTIONABLE,
            "个人文件目录，误删会造成数据丢失",
            "user-data",
        )

    # 可整体删除重建的开发环境依赖（node_modules、venv 等）
    if _is_rebuildable_cache_name(last):
        return RiskReport(
            target,
            RiskLevel.SAFE,
            "开发环境依赖，可整体删除后重建，但不建议手动修改内部文件",
            "rebuildable-cache-name",
        )

    # 缓存特征名称（优先于 AppData 规则，如 AppData\\Local\\Temp）；
    # 同级存在配置文件时降级为存疑——缓存可能保存了应用状态
    is_strong_cache = _is_strong_cache_name(last)
    if is_strong_cache or _is_weak_cache_name(last):
        if _has_config_sibling(target):
            return RiskReport(
                target,
                RiskLevel.QUESTIONABLE,
                "缓存目录，但同级存在配置文件，可能保存应用状态，建议关闭应用后清理",
                "cache-config-sibling",
            )
        if is_strong_cache:
            return RiskReport(
                target,
                RiskLevel.SAFE,
                "名称表明是缓存或临时目录，内容可自动重建",
                "strong-cache-name",
            )
        return RiskReport(
            target,
            RiskLevel.SAFE,
            "名称以 cache 结尾，通常为可安全清理的缓存",
            "weak-cache-name",
        )

    # AppData 规则（最长前缀优先）
    if first == "appdata":
        for segments, level, reason in _APPDATA_RULES:
            if under_user[: len(segments)] == segments:
                return RiskReport(target, level, reason, "appdata-prefix")

    # 用户根目录下的注册表配置单元及其事务日志（NTUSER.DAT.LOG1、{guid}.TxLog 等），
    # 不匹配 ntuser.ini 等用户自建文件
    if last.startswith("ntuser.dat"):
        return RiskReport(
            target,
            RiskLevel.HIGH,
            "用户注册表配置单元，损坏会导致无法登录",
            "ntuser-file",
        )

    # 点开头的开发工具/运行环境配置目录（.ssh、.docker 等）
    if first.startswith("."):
        return RiskReport(
            target,
            RiskLevel.QUESTIONABLE,
            "开发工具或运行环境的配置目录，删除会导致工具失去配置",
            "dot-dir",
        )

    # 其余目录根据内容元数据采样判断
    if target.is_dir():
        return _analyze_by_sampling(target)

    return RiskReport(
        target,
        RiskLevel.QUESTIONABLE,
        "未知内容，默认视为重要数据",
        "default",
    )


def _is_lexically_within_root(path: Path) -> bool:
    """按字面路径（不解析链接）判断是否位于根目录之下。"""
    normalized = Path(os.path.normpath(path))
    if not normalized.is_absolute():
        return False
    root_parts = [part.lower() for part in ROOT.parts]
    parts = [part.lower() for part in normalized.parts]
    return parts[: len(root_parts)] == root_parts and len(parts) > len(root_parts)


def _is_reparse_point(path: Path) -> bool:
    """判断是否为 junction 或符号链接等重解析点。"""
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat_mod.FILE_ATTRIBUTE_REPARSE_POINT)


def _is_strong_cache_name(name: str) -> bool:
    return name in _STRONG_CACHE_NAMES or (
        name.startswith(".") and name.endswith("_cache")
    )


def _is_rebuildable_cache_name(name: str) -> bool:
    return name in _REBUILDABLE_CACHE_NAMES


def _is_weak_cache_name(name: str) -> bool:
    return name.endswith(("cache", "caches"))


def _has_config_sibling(path: Path) -> bool:
    """检查缓存目录的同级文件里是否有配置文件（desktop.ini 等系统杂项除外）。"""
    try:
        with os.scandir(path.parent) as iterator:
            for entry in iterator:
                if entry.is_dir(follow_symlinks=False):
                    continue
                name = entry.name.lower()
                if name in _IGNORED_FILE_NAMES:
                    continue
                ext = name.rsplit(".", 1)[-1] if "." in name else ""
                if ext in _SIBLING_CONFIG_EXTS:
                    return True
    except OSError:
        return False
    return False


def _path_owner(path: Path) -> str | None:
    """返回目录所有者的“域名\\账户名”（如 NT AUTHORITY\\SYSTEM）；失败返回 None。"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    # SE_FILE_OBJECT=1，OWNER_SECURITY_INFORMATION=1；
    # owner_sid 指向 descriptor 内部，不能单独释放，最后整体释放 descriptor 即可
    owner_sid = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    # 超长路径需要扩展前缀，否则 API 会拒绝
    object_name = str(path)
    if len(object_name) >= 248:
        object_name = f"\\\\?\\{object_name}"
    result = ctypes.windll.advapi32.GetNamedSecurityInfoW(
        object_name,
        1,
        1,
        ctypes.byref(owner_sid),
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result != 0 or not owner_sid.value or not descriptor.value:
        return None
    try:
        name = ctypes.create_unicode_buffer(256)
        domain = ctypes.create_unicode_buffer(256)
        name_len = wintypes.DWORD(256)
        domain_len = wintypes.DWORD(256)
        use = wintypes.DWORD()
        if not ctypes.windll.advapi32.LookupAccountSidW(
            None,
            owner_sid,
            name,
            ctypes.byref(name_len),
            domain,
            ctypes.byref(domain_len),
            ctypes.byref(use),
        ):
            return None
        if domain.value:
            return f"{domain.value}\\{name.value}"
        return name.value
    finally:
        ctypes.windll.kernel32.LocalFree(descriptor)


def _is_system_owner(owner: str) -> bool:
    """所有者账户名是否为 SYSTEM 或 TrustedInstaller 等系统主体。"""
    account = owner.rsplit("\\", 1)[-1].strip().lower()
    return account in _SYSTEM_OWNER_ACCOUNTS


def _analyze_by_sampling(path: Path) -> RiskReport:
    """扫描目录内文件的元数据，推断风险等级。"""
    try:
        stat_result = path.stat()
    except OSError:
        return _unknown(path, "无法读取目录属性，默认视为重要数据")

    attributes = getattr(stat_result, "st_file_attributes", 0)
    if attributes & stat_mod.FILE_ATTRIBUTE_SYSTEM:
        return RiskReport(
            path,
            RiskLevel.HIGH,
            "目录带有系统属性，可能为系统组件",
            "sample-system-attribute",
        )

    # 所有者为 SYSTEM / TrustedInstaller 的目录不是用户数据（如 Public、Default）
    owner = _path_owner(path)
    if owner is not None and _is_system_owner(owner):
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            f"目录所有者为 {owner}，疑似系统组件而非用户数据",
            "sample-system-owner",
        )

    file_count = 0
    cache_count = 0
    has_config = False
    has_hive = False
    has_veto_config = False
    try:
        with os.scandir(path) as iterator:
            for index, entry in enumerate(iterator):
                if index >= _SAMPLE_LIMIT:
                    break
                name = entry.name.lower()
                if name.startswith("ntuser.dat") or name in _HIVE_NAMES:
                    has_hive = True
                    break  # 配置单元足以定性，无需继续采样
                if name in _IGNORED_FILE_NAMES:
                    continue  # 系统自动生成的杂项文件不参与判定
                if entry.is_dir(follow_symlinks=False):
                    continue
                file_count += 1
                ext = name.rsplit(".", 1)[-1] if "." in name else ""
                if ext in _CACHE_EXTS or "cache" in name:
                    cache_count += 1
                if ext in _CONFIG_EXTS:
                    has_config = True
                    if ext in _VETO_CONFIG_EXTS:
                        # 重要配置（.json/.ini/.dat）一票否决“安全”，无需继续采样
                        has_veto_config = True
                        break
    except OSError:
        return _unknown(path)

    if has_hive:
        return RiskReport(
            path,
            RiskLevel.HIGH,
            "包含注册表配置单元文件，损坏会导致无法登录",
            "sample-registry-hive",
        )
    if has_veto_config:
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            "包含 .json/.ini/.dat 等重要配置文件，不建议清理",
            "sample-veto-config",
        )
    if file_count == 0:
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            "目录为空，无法根据内容判断",
            "sample-empty",
        )
    if file_count >= 8 and cache_count / file_count >= 0.8:
        return RiskReport(
            path,
            RiskLevel.SAFE,
            "内容以缓存和临时文件为主，可安全清理",
            "sample-cache-heavy",
        )
    if has_config:
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            "包含应用配置或数据库文件，删除会导致应用失去记录",
            "sample-config-files",
        )
    return _unknown(path, "无法确定内容，默认视为重要数据")


def _unknown(
    path: Path, reason: str = "无法读取目录内容，默认视为重要数据"
) -> RiskReport:
    return RiskReport(path, RiskLevel.QUESTIONABLE, reason, "unknown")
