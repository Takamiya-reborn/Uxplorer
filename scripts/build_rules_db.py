"""从 rules_seed.sql 生成规则库 rules.db。

用法：
    uv run scripts/build_rules_db.py            # 写入 src/uxplorer/resources/rules.db
    uv run scripts/build_rules_db.py -o 别处.db  # 写入指定路径
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
SEED_PATH = _SCRIPTS_DIR / "rules_seed.sql"
DEFAULT_OUTPUT = _SCRIPTS_DIR.parent / "src" / "uxplorer" / "resources" / "rules.db"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出的 db 文件路径（默认: %(default)s）",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(args.output)
    try:
        connection.executescript(SEED_PATH.read_text(encoding="utf-8"))
        connection.commit()
        rule_count = connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        param_count = connection.execute("SELECT COUNT(*) FROM params").fetchone()[0]
    finally:
        connection.close()

    print(f"已生成 {args.output}：{rule_count} 条规则，{param_count} 个参数")


if __name__ == "__main__":
    main()
