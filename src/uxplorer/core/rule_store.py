"""加载并编译 SQLite 规则库 rules.db。

规则库随包分发（src/uxplorer/resources/rules.db，由
scripts/rules_seed.sql 生成），启动后首次使用时以只读方式一次性载入
内存，之后的分析不再访问数据库文件。

容错策略：规则库缺失、损坏或校验不通过时，返回 available=False 的
回退规则集——引擎据此对所有路径给出“存疑”的保守判定，而不是让
应用崩溃。校验是严格的：任何一行数据非法（未知 match_type、非法
等级、缺失必需参数、schema 版本不符）都视为整个规则库不可用。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..resources import resource_path

__all__ = ["Rule", "RuleSet", "load_rule_set", "get_rule_set"]

_SCHEMA_VERSION = "2"

_VALID_MATCH_TYPES = frozenset(
    {
        "first_segment_exact",
        "first_segment_prefix",
        "any_segment_exact",
        "last_segment_exact",
        "last_segment_prefix",
        "last_segment_suffix",
        "last_segment_regex",
        "path_exact",
        "path_prefix",
    }
)
_VALID_LEVELS = frozenset({"high", "caution", "safe"})

# 引擎正常运行所必需的参数键（采样判定使用）
_REQUIRED_PARAMS = (
    "hive_names",
    "cache_exts",
    "config_exts",
    "veto_config_exts",
    "ignored_file_names",
    "system_owner_accounts",
    "sample_limit",
    "cache_heavy_ratio",
    "cache_heavy_min_files",
)

# 判断相对用户根目录的段序列（under_user）是否命中规则
Matcher = Callable[[tuple[str, ...]], bool]


@dataclass(frozen=True)
class Rule:
    """一条静态匹配规则（rules 表中的一行）。"""

    rule_id: str
    priority: int
    match_type: str
    pattern: str
    level: str
    delete_risk: str | None
    modify_risk: str | None
    is_container: bool
    reason: str
    advice: str


@dataclass(frozen=True)
class RuleSet:
    """编译后的规则集合。

    matchers 按 (priority 升序, path_prefix 段数降序, 行序) 排列，
    引擎依次检查、首个命中生效。available=False 表示规则库不可用，
    此时 rules/matchers/params 均为空。
    """

    available: bool = False
    rules: tuple[Rule, ...] = ()
    matchers: tuple[tuple[Rule, Matcher], ...] = ()
    params: dict[str, str] = field(default_factory=dict)

    def param(self, key: str) -> str:
        """读取文本参数。必需键在加载时已校验存在。"""
        return self.params[key]

    def param_set(self, key: str) -> frozenset[str]:
        """读取逗号分隔的集合参数。"""
        return frozenset(
            item.strip() for item in self.params[key].split(",") if item.strip()
        )

    def param_int(self, key: str) -> int:
        return int(self.params[key])

    def param_float(self, key: str) -> float:
        return float(self.params[key])


_FALLBACK_RULE_SET = RuleSet()


def load_rule_set(path: str | Path) -> RuleSet:
    """从指定路径加载规则库；缺失、损坏或校验不通过时返回回退规则集。"""
    try:
        db_path = Path(path).resolve()
        # 只读打开：规则库随包分发，不应被应用意外修改
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    except (OSError, ValueError, sqlite3.Error):
        return _FALLBACK_RULE_SET
    try:
        return _load_from_connection(connection)
    except (sqlite3.Error, ValueError, KeyError):
        return _FALLBACK_RULE_SET
    finally:
        connection.close()


def get_rule_set() -> RuleSet:
    """获取包内规则库（首次调用时加载并缓存）。"""
    global _rule_set
    if _rule_set is None:
        _rule_set = load_rule_set(resource_path("rules.db"))
    return _rule_set


_rule_set: RuleSet | None = None


def _load_from_connection(connection: sqlite3.Connection) -> RuleSet:
    version = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if version is None or version[0] != _SCHEMA_VERSION:
        raise ValueError(f"不支持的规则库版本: {version}")

    params = dict(connection.execute("SELECT key, value FROM params"))
    missing = [key for key in _REQUIRED_PARAMS if key not in params]
    if missing:
        raise ValueError(f"规则库缺少必需参数: {missing}")

    rules: list[tuple[int, Rule]] = []
    for row in connection.execute(
        "SELECT id, rule_id, priority, match_type, pattern, level,"
        " delete_risk, modify_risk, is_container, reason, advice"
        " FROM rules WHERE enabled = 1"
    ):
        rules.append((row[0], _parse_rule(row)))

    # path_prefix 同优先级内段数最长者优先，保证最长前缀匹配语义
    compiled = sorted(
        ((rule, _compile_matcher(rule)) for _, rule in rules),
        key=lambda pair: (
            pair[0].priority,
            -pair[0].pattern.count("/") if pair[0].match_type == "path_prefix" else 0,
            # 稳定排序保持同优先级内的行序
        ),
    )
    return RuleSet(
        available=True,
        rules=tuple(rule for _, rule in rules),
        matchers=tuple(compiled),
        params=params,
    )


def _parse_rule(row: tuple) -> Rule:
    (
        _id,
        rule_id,
        priority,
        match_type,
        pattern,
        level,
        delete_risk,
        modify_risk,
        is_container,
        reason,
        advice,
    ) = row
    if match_type not in _VALID_MATCH_TYPES:
        raise ValueError(f"未知 match_type: {match_type}")
    if match_type == "path_prefix" and not pattern:
        raise ValueError("path_prefix 规则的 pattern 不能为空")
    if level not in _VALID_LEVELS:
        raise ValueError(f"非法等级: {level}")
    for optional in (delete_risk, modify_risk):
        if optional is not None and optional not in _VALID_LEVELS:
            raise ValueError(f"非法等级: {optional}")
    return Rule(
        rule_id=rule_id,
        priority=priority,
        match_type=match_type,
        pattern=pattern,
        level=level,
        delete_risk=delete_risk,
        modify_risk=modify_risk,
        is_container=bool(is_container),
        reason=reason,
        advice=advice,
    )


def _compile_matcher(rule: Rule) -> Matcher:
    """把一条规则编译成针对 under_user 段序列的匹配函数。

    under_user 是目标路径相对用户根目录的小写段序列，如
    C:\\Users\\Bob\\AppData\\Local → ('appdata', 'local')；空序列表示
    C:\\Users 下的直接子目录（用户配置文件根）。
    """
    match_type = rule.match_type
    pattern = rule.pattern

    if match_type == "first_segment_exact":
        return lambda segments: bool(segments) and segments[0] == pattern
    if match_type == "first_segment_prefix":
        return lambda segments: bool(segments) and segments[0].startswith(pattern)
    if match_type == "any_segment_exact":
        # 路径中任意一段命中即匹配（如 node_modules/x/node_modules 的嵌套依赖目录）
        return lambda segments: pattern in segments
    if match_type == "last_segment_exact":
        return lambda segments: bool(segments) and segments[-1] == pattern
    if match_type == "last_segment_prefix":
        return lambda segments: bool(segments) and segments[-1].startswith(pattern)
    if match_type == "last_segment_suffix":
        return lambda segments: bool(segments) and segments[-1].endswith(pattern)
    if match_type == "last_segment_regex":
        regex = re.compile(pattern)
        return (
            lambda segments: bool(segments)
            and regex.fullmatch(segments[-1]) is not None
        )
    if match_type == "path_exact":
        expected = tuple(pattern.split("/")) if pattern else ()
        return lambda segments: segments == expected
    # path_prefix
    expected = tuple(pattern.split("/"))
    length = len(expected)
    return lambda segments: len(segments) >= length and segments[:length] == expected
