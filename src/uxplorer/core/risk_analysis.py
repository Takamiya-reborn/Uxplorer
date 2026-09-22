"""分析 C:\\Users 下目录的重要程度，评估手动更改的风险等级。

等级定义（以“应用能否继续正常工作”为标准）：
- 高危：手动更改会导致系统无法正常运行；
- 存疑：手动更改会导致某些应用失去记录或者无法正常运行；
- 安全：删除后应用仍可正常工作，内容会自动重建或从网络重新下载，
  代价（如需重新下载依赖、丢失对话历史）在 advice 中提醒。

除综合等级外，结果还区分“删除风险”与“修改风险”两个维度：
有些目录删除安全但修改危险（如 node_modules），有些目录删除会丢数据
但修改内容无妨（如 Desktop）。“容器”类目录（如用户根目录）本身
不可删除或重命名，但内部子项可独立管理。

具体规则（名称/前缀匹配表、采样参数）由 SQLite 规则库 rules.db 提供
（见 rule_store.py 与 scripts/rules_seed.sql）；本模块只保留匹配
引擎与采样逻辑。规则库缺失或损坏时，所有路径保守回退为“存疑”。
"""

from __future__ import annotations

import os
import stat as stat_mod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .api import ROOT, is_within_root
from .rule_store import RuleSet, get_rule_set

__all__ = ["RiskLevel", "RiskReport", "analyze_risk", "path_access_summary"]


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
    """风险分析结果。

    level 是用于展示的综合等级；删除与修改两个维度未显式给出时
    （None）与综合等级一致。
    """

    path: Path
    level: RiskLevel
    reason: str
    rule: str
    delete_risk: RiskLevel | None = None  # 删除整个目录的风险
    modify_risk: RiskLevel | None = None  # 手动修改内部文件的风险
    is_container: bool = False  # 容器：本身不可动，但子项可独立管理
    advice: str = ""  # 具体操作建议
    evidence: str = ""  # 采样证据（动态生成的数字或文件特征）

    @property
    def delete_level(self) -> RiskLevel:
        return self.delete_risk if self.delete_risk is not None else self.level

    @property
    def modify_level(self) -> RiskLevel:
        return self.modify_risk if self.modify_risk is not None else self.level


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

    # 相对用户根目录的小写段序列（如 AppData\Local → ('appdata', 'local')）；
    # 空序列表示 C:\Users 下的直接子目录（用户配置文件根）
    under_user = tuple(part.lower() for part in target.relative_to(ROOT).parts[1:])

    # 越界与系统链接检查不依赖规则库，仍正常工作
    rules = get_rule_set()
    if not rules.available:
        return RiskReport(
            target,
            RiskLevel.QUESTIONABLE,
            "规则库缺失或损坏，默认视为重要数据",
            "rules-missing",
        )

    # 静态规则：按优先级依次检查，首个命中生效
    for rule, matcher in rules.matchers:
        if matcher(under_user):
            return RiskReport(
            target,
            RiskLevel(rule.level),
            rule.reason,
            rule.rule_id,
            delete_risk=_optional_level(rule.delete_risk),
            modify_risk=_optional_level(rule.modify_risk),
            is_container=rule.is_container,
            advice=rule.advice,
        )

    # 其余目录根据内容元数据采样判断
    if target.is_dir():
        return _analyze_by_sampling(target, rules)

    return RiskReport(
        target,
        RiskLevel.QUESTIONABLE,
        "未知内容，默认视为重要数据",
        "default",
    )


def _optional_level(value: str | None) -> RiskLevel | None:
    """把规则库中的等级文本转换为 RiskLevel；空值保持 None（跟随综合等级）。"""
    return RiskLevel(value) if value else None


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


def _path_owner(path: Path) -> str | None:
    """返回目录所有者的“域名\\账户名”（如 NT AUTHORITY\\SYSTEM）；失败返回 None。"""
    if os.name != "nt":
        return None
    import ctypes

    # SE_FILE_OBJECT=1，OWNER_SECURITY_INFORMATION=1；
    # owner_sid 指向 descriptor 内部，不能单独释放，最后整体释放 descriptor 即可
    owner_sid = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    if _get_named_security_info(str(path), 1, owner_sid, None, descriptor):
        return None
    try:
        return _sid_to_account(owner_sid)
    finally:
        ctypes.windll.kernel32.LocalFree(descriptor)


def path_access_summary(path: Path) -> str | None:
    """目录的访问控制摘要，供提示词生成使用。

    返回如 "所有者：NT AUTHORITY\\SYSTEM；访问控制：
    SYSTEM 完全控制、Administrators 完全控制、<用户名> 修改"；
    非 Windows 或读取失败时返回 None。账户名可能含真实用户名，
    调用方需自行脱敏。
    """
    if os.name != "nt":
        return None
    import ctypes

    # SE_FILE_OBJECT=1，OWNER|DACL_SECURITY_INFORMATION=1|4=5
    owner_sid = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    if _get_named_security_info(str(path), 5, owner_sid, dacl, descriptor):
        return None
    try:
        parts = []
        owner = _sid_to_account(owner_sid)
        if owner:
            parts.append(f"所有者：{owner}")
        if dacl.value:
            entries = _dacl_entries(dacl)
            if entries:
                parts.append("访问控制：" + "、".join(entries))
        return "；".join(parts) if parts else None
    finally:
        ctypes.windll.kernel32.LocalFree(descriptor)


def _get_named_security_info(
    object_name: str,
    security_info: int,
    owner_sid,
    dacl,
    descriptor,
) -> int:
    """GetNamedSecurityInfoW 的薄封装；返回错误码（0 表示成功）。

    owner_sid / dacl / descriptor 均为 ctypes.c_void_p，由调用方释放 descriptor。
    """
    import ctypes

    # 超长路径需要扩展前缀，否则 API 会拒绝
    if len(object_name) >= 248:
        object_name = f"\\\\?\\{object_name}"
    # 参数依次为：对象名、SE_FILE_OBJECT、信息类别、owner、group、dacl、sacl、descriptor
    return ctypes.windll.advapi32.GetNamedSecurityInfoW(
        object_name,
        1,
        security_info,
        ctypes.byref(owner_sid) if owner_sid is not None else None,
        None,
        ctypes.byref(dacl) if dacl is not None else None,
        None,
        ctypes.byref(descriptor),
    )


def _sid_to_account(sid) -> str | None:
    """SID -> “域名\\账户名”；失败返回 None。"""
    import ctypes
    from ctypes import wintypes

    name = ctypes.create_unicode_buffer(256)
    domain = ctypes.create_unicode_buffer(256)
    name_len = wintypes.DWORD(256)
    domain_len = wintypes.DWORD(256)
    use = wintypes.DWORD()
    if not ctypes.windll.advapi32.LookupAccountSidW(
        None,
        sid,
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


# 访问掩码分类用的位（含通用权限位与目录的特定权限位）
_MASK_FULL = 0x10000000 | 0x001F01FF  # GENERIC_ALL | FILE_ALL_ACCESS
_MASK_WRITE = 0x40000000 | 0x2 | 0x4 | 0x10000  # GENERIC_WRITE | 建文件/建目录 | DELETE
_MASK_READ = 0x80000000 | 0x1 | 0x20000  # GENERIC_READ | 列目录 | READ_CONTROL
# 访问控制摘要里最多列出的账户数，其余合并为“等”
_MAX_ACL_ACCOUNTS = 6
# 权限高低的排序依据，同一账户出现多条 ACE 时保留最高一条
_LEVEL_RANK = {"完全控制": 2, "修改": 1, "读取": 0}


def _dacl_entries(dacl) -> list[str]:
    """把 DACL 压缩为“账户 权限”列表；同一账户保留最高权限。"""
    import ctypes
    from ctypes import wintypes

    class _ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    # ACCESS_ALLOWED_ACE / ACCESS_DENIED_ACE 布局相同：
    # ACE_HEADER(4字节) + Mask(4字节) + SidStart(SID 起始)
    class _ACE(ctypes.Structure):
        _fields_ = [
            ("AceType", wintypes.BYTE),
            ("AceFlags", wintypes.BYTE),
            ("AceSize", wintypes.WORD),
            ("Mask", wintypes.DWORD),
            ("SidStart", wintypes.DWORD),
        ]

    info = _ACL_SIZE_INFORMATION()
    # ACLSecurityInformation = 2（AclSizeInformation）
    if not ctypes.windll.advapi32.GetAclInformation(
        dacl, ctypes.byref(info), ctypes.sizeof(info), 2
    ):
        return []

    best: dict[str, str] = {}
    for i in range(info.AceCount):
        ace = ctypes.c_void_p()
        if not ctypes.windll.advapi32.GetAce(dacl, i, ctypes.byref(ace)) or not ace.value:
            continue
        ace_struct = ctypes.cast(ace, ctypes.POINTER(_ACE)).contents
        account = _sid_to_account(
            ctypes.c_void_p(ctypes.addressof(ace_struct) + _ACE.SidStart.offset)
        )
        if not account:
            continue
        mask = ace_struct.Mask
        if mask & _MASK_FULL:
            level = "完全控制"
        elif mask & _MASK_WRITE:
            level = "修改"
        elif mask & _MASK_READ:
            level = "读取"
        else:
            level = "特殊权限"
        if ace_struct.AceType == 1:  # ACCESS_DENIED_ACE_TYPE
            level = f"拒绝{level}"
        if account not in best or _LEVEL_RANK.get(level, -1) > _LEVEL_RANK.get(
            best[account], -1
        ):
            best[account] = level
    entries = [f"{account} {level}" for account, level in best.items()]
    if len(entries) > _MAX_ACL_ACCOUNTS:
        entries = entries[:_MAX_ACL_ACCOUNTS]
        entries.append("等")
    return entries


def _is_system_owner(owner: str, accounts: frozenset[str]) -> bool:
    """所有者账户名是否为 SYSTEM 或 TrustedInstaller 等系统主体。"""
    account = owner.rsplit("\\", 1)[-1].strip().lower()
    return account in accounts


def _analyze_by_sampling(path: Path, rules: RuleSet) -> RiskReport:
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
    if owner is not None and _is_system_owner(
        owner, rules.param_set("system_owner_accounts")
    ):
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            f"目录所有者为 {owner}，疑似系统组件而非用户数据",
            "sample-system-owner",
        )

    hive_names = rules.param_set("hive_names")
    ignored_names = rules.param_set("ignored_file_names")
    cache_exts = rules.param_set("cache_exts")
    config_exts = rules.param_set("config_exts")
    veto_exts = rules.param_set("veto_config_exts")
    sample_limit = rules.param_int("sample_limit")
    cache_heavy_ratio = rules.param_float("cache_heavy_ratio")
    cache_heavy_min_files = rules.param_int("cache_heavy_min_files")

    file_count = 0
    dir_count = 0
    cache_count = 0
    has_config = False
    has_hive = False
    has_veto_config = False
    veto_names: list[str] = []
    try:
        with os.scandir(path) as iterator:
            for index, entry in enumerate(iterator):
                if index >= sample_limit:
                    break
                name = entry.name.lower()
                if name.startswith("ntuser.dat") or name in hive_names:
                    has_hive = True
                    break  # 配置单元足以定性，无需继续采样
                if name in ignored_names:
                    continue  # 系统自动生成的杂项文件不参与判定
                if entry.is_dir(follow_symlinks=False):
                    dir_count += 1
                    continue
                file_count += 1
                ext = name.rsplit(".", 1)[-1] if "." in name else ""
                if ext in cache_exts or "cache" in name:
                    cache_count += 1
                if ext in config_exts:
                    has_config = True
                    if ext in veto_exts:
                        # 重要配置（.json/.ini/.dat）一票否决“安全”，无需继续采样
                        has_veto_config = True
                        if len(veto_names) < 3:
                            veto_names.append(entry.name)
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
            "包含 .json/.ini/.dat 等重要配置文件，手动修改可能导致应用崩溃"
            "或数据丢失，建议仅备份不修改",
            "sample-veto-config",
            evidence=f"采样发现 {'、'.join(veto_names)} 等配置文件",
        )
    if file_count == 0 and dir_count == 0:
        return RiskReport(
            path,
            RiskLevel.SAFE,
            "空目录，删除后应用需要时会自动重建",
            "sample-empty",
        )
    if file_count == 0:
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            "目录下只有子文件夹，无法直接判断内容",
            "sample-subdirs-only",
        )
    if (
        file_count >= cache_heavy_min_files
        and cache_count / file_count >= cache_heavy_ratio
    ):
        return RiskReport(
            path,
            RiskLevel.SAFE,
            f"采样 {file_count} 个文件，{cache_count} 个为缓存或临时文件，可安全清理",
            "sample-cache-heavy",
        )
    if has_config:
        return RiskReport(
            path,
            RiskLevel.QUESTIONABLE,
            "采样发现配置与数据库文件，删除会导致应用失去记录",
            "sample-config-files",
        )
    return _unknown(path, "无法确定内容，默认视为重要数据")


def _unknown(
    path: Path, reason: str = "无法读取目录内容，默认视为重要数据"
) -> RiskReport:
    return RiskReport(path, RiskLevel.QUESTIONABLE, reason, "unknown")
