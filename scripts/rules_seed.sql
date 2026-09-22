-- Uxplorer 风险分析规则库种子数据
-- 用 scripts/build_rules_db.py 生成 src/uxplorer/resources/rules.db。
-- 也可以直接用 DB Browser 编辑 rules.db（应用重启后生效）。
--
-- 匹配语义（引擎在 risk_analysis.py 中实现）：
-- - 目标路径转换为相对用户根目录的小写段序列 under_user
--   （如 C:\Users\Bob\AppData\Local → ('appdata', 'local')）；
--   序列为空表示 C:\Users 下的直接子目录（用户配置文件根）。
-- - 规则按 (priority 升序, path_prefix 段数降序, id 升序) 依次检查，首个命中生效。
-- - level / delete_risk / modify_risk 取值：high / caution / safe；
--   delete_risk、modify_risk 为 NULL 时与 level 一致。
-- - 分级标准是“应用能否继续正常工作”：删除后内容可自动重建或重新下载的
--   都算 safe，代价（重新下载、丢失历史记录）写在 advice 里提醒。
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS rules;

DROP TABLE IF EXISTS params;

DROP TABLE IF EXISTS meta;

CREATE TABLE
        rules (
                id INTEGER PRIMARY KEY,
                rule_id TEXT NOT NULL, -- 写入 RiskReport.rule 的稳定标识（可多行同名）
                priority INTEGER NOT NULL, -- 引擎按此顺序检查，小者先
                match_type TEXT NOT NULL, -- 匹配方式，见上方说明
                pattern TEXT NOT NULL, -- path_* 类用 '/' 分隔的相对路径段；'' 表示用户根本身
                level TEXT NOT NULL, -- 'high' | 'caution' | 'safe'
                delete_risk TEXT, -- 可空，空 = 与 level 一致
                modify_risk TEXT, -- 可空，空 = 与 level 一致
                is_container INTEGER NOT NULL DEFAULT 0, -- 容器：本身不可动，子项可独立管理
                reason TEXT NOT NULL,
                advice TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1
        );

CREATE TABLE
        params (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL -- 集合类用逗号分隔，数值直接存文本
        );

CREATE TABLE
        meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

INSERT INTO
        meta (key, value)
VALUES
        ('schema_version', '2');

-- ---------------------------------------------------------------- priority 10
-- 用户配置文件根目录（C:\Users 下的直接子目录，包括用户名、Default、Public）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                is_container,
                reason,
                advice
        )
VALUES
        (
                1,
                'profile-root',
                10,
                'path_exact',
                '',
                'high',
                1,
                '用户配置文件根目录，直接删除或重命名整个目录会导致无法登录',
                '根目录本身不可动，但内部子文件夹（如 Desktop、Documents）可进入后独立管理'
        );

-- ---------------------------------------------------------------- priority 15
-- 可整体删除后由工具链重建的开发环境依赖目录（含其内部与嵌套形式，
-- 如 node_modules/x/node_modules），删除与修改都安全，重建代价见 advice。
-- 优先于个人数据目录规则：node_modules 无论在 Desktop 还是 OneDrive 下，
-- 名称信号都比位置信号更明确
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                16,
                'rebuildable-cache-name',
                15,
                'any_segment_exact',
                'node_modules',
                'safe',
                '开发环境依赖目录，删除后重新安装即可重建',
                '删除后重新安装依赖时需从网络重新下载（如 npm install）'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                17,
                'rebuildable-cache-name',
                15,
                'any_segment_exact',
                '__pycache__',
                'safe',
                '开发环境依赖目录，删除后重新运行即可重建',
                '删除后 Python 会在下次运行时重新生成字节码'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                18,
                'rebuildable-cache-name',
                15,
                'any_segment_exact',
                'venv',
                'safe',
                'Python 虚拟环境，删除后可重新创建',
                '删除后需重新创建虚拟环境并重新安装依赖（从网络下载）'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                19,
                'rebuildable-cache-name',
                15,
                'any_segment_exact',
                '.venv',
                'safe',
                'Python 虚拟环境，删除后可重新创建',
                '删除后需重新创建虚拟环境并重新安装依赖（从网络下载）'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                20,
                'rebuildable-cache-name',
                15,
                'any_segment_exact',
                'pnpm-store',
                'safe',
                'pnpm 依赖存储目录，删除后重新安装即可重建',
                '删除后重新安装依赖时需从网络重新下载'
        );

-- ---------------------------------------------------------------- priority 20
-- OneDrive 同步目录（精确的 OneDrive，或 "OneDrive - 公司" 形式的变体；
-- 不匹配用户自建的 OneDriveBackup 之类文件夹）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                2,
                'onedrive',
                20,
                'first_segment_exact',
                'onedrive',
                'caution',
                'safe',
                'OneDrive 同步的个人文件，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                3,
                'onedrive',
                20,
                'first_segment_prefix',
                'onedrive -',
                'caution',
                'safe',
                'OneDrive 同步的个人文件，误删会造成数据丢失'
        );

-- ---------------------------------------------------------------- priority 30
-- 个人数据目录（用户根目录下的第一段），误删会造成数据丢失；
-- 删除丢数据，但修改内容无妨
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                4,
                'user-data',
                30,
                'first_segment_exact',
                'desktop',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                5,
                'user-data',
                30,
                'first_segment_exact',
                'documents',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                6,
                'user-data',
                30,
                'first_segment_exact',
                'downloads',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                7,
                'user-data',
                30,
                'first_segment_exact',
                'pictures',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                8,
                'user-data',
                30,
                'first_segment_exact',
                'music',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                9,
                'user-data',
                30,
                'first_segment_exact',
                'videos',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                10,
                'user-data',
                30,
                'first_segment_exact',
                'favorites',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                11,
                'user-data',
                30,
                'first_segment_exact',
                'contacts',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                12,
                'user-data',
                30,
                'first_segment_exact',
                'links',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                13,
                'user-data',
                30,
                'first_segment_exact',
                'saved games',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                14,
                'user-data',
                30,
                'first_segment_exact',
                'searches',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                modify_risk,
                reason
        )
VALUES
        (
                15,
                'user-data',
                30,
                'first_segment_exact',
                '3d objects',
                'caution',
                'safe',
                '个人文件目录，误删会造成数据丢失'
        );

-- ---------------------------------------------------------------- priority 25
-- AI 工具的会话记录与包缓存：删除不影响应用运行，目录会自动重建
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                40,
                'ai-session-data',
                25,
                'path_prefix',
                '.claude/projects',
                'safe',
                'AI 助手的对话记录与任务历史',
                '删除后 Claude Code 会重新创建目录，但历史对话将丢失'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                41,
                'ai-session-data',
                25,
                'path_prefix',
                '.claude/todos',
                'safe',
                'AI 助手的临时任务清单',
                '删除后 Claude Code 需要时会重新创建'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                42,
                'ai-session-data',
                25,
                'path_prefix',
                '.claude/shell-snapshots',
                'safe',
                'AI 助手的 shell 环境快照',
                '删除后 Claude Code 需要时会重新创建'
        );

-- 工具链的下载/缓存目录（含 huggingface 模型缓存等大目录）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                43,
                'tool-download-cache',
                25,
                'first_segment_exact',
                '.cache',
                'safe',
                '工具链的缓存目录',
                '删除后各工具需要时会重新下载或重建缓存'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason,
                advice
        )
VALUES
        (
                44,
                'tool-download-cache',
                25,
                'first_segment_exact',
                '.npm',
                'safe',
                'npm 的包缓存目录',
                '删除后 npm 会在下次安装时从网络重新下载'
        );

-- ---------------------------------------------------------------- priority 50
-- 强缓存特征名称：在任何位置出现都视为缓存，可清理。
-- 优先于 AppData 前缀规则（如 AppData\Local\Temp）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                21,
                'strong-cache-name',
                50,
                'last_segment_exact',
                'temp',
                'safe',
                '名称表明是缓存或临时目录，内容可自动重建'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                22,
                'strong-cache-name',
                50,
                'last_segment_exact',
                'tmp',
                'safe',
                '名称表明是缓存或临时目录，内容可自动重建'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                23,
                'strong-cache-name',
                50,
                'last_segment_exact',
                'crashpad',
                'safe',
                '名称表明是缓存或临时目录，内容可自动重建'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                24,
                'strong-cache-name',
                50,
                'last_segment_exact',
                '.temp',
                'safe',
                '名称表明是缓存或临时目录，内容可自动重建'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                25,
                'strong-cache-name',
                50,
                'last_segment_exact',
                '.tmp',
                'safe',
                '名称表明是缓存或临时目录，内容可自动重建'
        );

-- “.xxx_cache” 形式的缓存目录（如 .vscode_cache）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                26,
                'strong-cache-name',
                50,
                'last_segment_regex',
                '^\..*_cache$',
                'safe',
                '名称表明是缓存或临时目录，内容可自动重建'
        );

-- ---------------------------------------------------------------- priority 51
-- 弱缓存特征名称。
-- 注意：logs/log 只做精确匹配——catalog、dialog 等也以 log 结尾，按前缀匹配会误判
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                27,
                'weak-cache-name',
                51,
                'last_segment_suffix',
                'cache',
                'safe',
                '应用产生的缓存或日志，清理后会自动重建；建议先关闭对应应用再清理'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                28,
                'weak-cache-name',
                51,
                'last_segment_suffix',
                'caches',
                'safe',
                '应用产生的缓存或日志，清理后会自动重建；建议先关闭对应应用再清理'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                29,
                'weak-cache-name',
                51,
                'last_segment_exact',
                'logs',
                'safe',
                '应用产生的缓存或日志，清理后会自动重建；建议先关闭对应应用再清理'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                30,
                'weak-cache-name',
                51,
                'last_segment_exact',
                'log',
                'safe',
                '应用产生的缓存或日志，清理后会自动重建；建议先关闭对应应用再清理'
        );

-- ---------------------------------------------------------------- priority 60
-- AppData 根目录是容器：本身不可删除，但内部各应用子目录风险各异
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                is_container,
                reason,
                advice
        )
VALUES
        (
                31,
                'appdata-prefix',
                60,
                'path_exact',
                'appdata',
                'high',
                1,
                'AppData 根目录，删除会同时破坏系统组件与应用数据',
                'AppData 根目录本身不可删除，内部各应用的子目录风险各异，应逐个查看'
        );

-- ---------------------------------------------------------------- priority 70
-- AppData 前缀规则（同优先级内段数最长者优先）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                32,
                'appdata-prefix',
                70,
                'path_prefix',
                'appdata/local/microsoft/windows',
                'high',
                '包含 UsrClass.dat 注册表配置单元等系统关键数据'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                33,
                'appdata-prefix',
                70,
                'path_prefix',
                'appdata/local/microsoft',
                'caution',
                '微软组件的用户数据与配置'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                34,
                'appdata-prefix',
                70,
                'path_prefix',
                'appdata/local/packages',
                'caution',
                'UWP 应用沙盒数据，误删会导致应用重置或需要重新登录'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                35,
                'appdata-prefix',
                70,
                'path_prefix',
                'appdata/local',
                'caution',
                '应用本地数据与配置'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                36,
                'appdata-prefix',
                70,
                'path_prefix',
                'appdata/roaming',
                'caution',
                '应用漫游数据与配置'
        );

INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                37,
                'appdata-prefix',
                70,
                'path_prefix',
                'appdata/locallow',
                'caution',
                '应用低完整性级别数据'
        );

-- ---------------------------------------------------------------- priority 80
-- 用户根目录下的注册表配置单元及其事务日志（NTUSER.DAT.LOG1、{guid}.TxLog 等），
-- 不匹配 ntuser.ini 等用户自建文件
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                38,
                'ntuser-file',
                80,
                'last_segment_prefix',
                'ntuser.dat',
                'high',
                '用户注册表配置单元，损坏会导致无法登录'
        );

-- ---------------------------------------------------------------- priority 90
-- 点开头的开发工具/运行环境配置目录（.ssh、.docker 等）
INSERT INTO
        rules (
                id,
                rule_id,
                priority,
                match_type,
                pattern,
                level,
                reason
        )
VALUES
        (
                39,
                'dot-dir',
                90,
                'first_segment_prefix',
                '.',
                'caution',
                '开发工具或运行环境的配置目录，删除会导致工具失去配置'
        );

-- ==================================================================== params
-- 采样与辅助判定使用的参数（引擎 _analyze_by_sampling 等处消费）。
-- 集合类参数用逗号分隔。
-- 注册表配置单元文件名
INSERT INTO
        params (key, value)
VALUES
        ('hive_names', 'ntuser.dat,usrclass.dat');

-- 缓存文件扩展名
INSERT INTO
        params (key, value)
VALUES
        ('cache_exts', 'tmp,temp,log,bak,old,dmp');

-- 配置文件扩展名
INSERT INTO
        params (key, value)
VALUES
        (
                'config_exts',
                'json,ini,cfg,conf,db,dat,xml,sqlite'
        );

-- 重要配置扩展名：出现即可一票否决“安全”判定。
-- 不含 .json（程序生成极常见，多可重建）与 .db/.sqlite（常与 .log 形式
-- 的 WAL 日志混放）——这类目录交给缓存比例判定处理
INSERT INTO
        params (key, value)
VALUES
        ('veto_config_exts', 'ini,dat');

-- 系统自动生成的杂项文件，不参与内容与同级判定
INSERT INTO
        params (key, value)
VALUES
        ('ignored_file_names', 'desktop.ini,thumbs.db');

-- 视为系统组件的目录所有者账户名
INSERT INTO
        params (key, value)
VALUES
        (
                'system_owner_accounts',
                'system,trustedinstaller'
        );

-- 采样上限（目录内最多检查多少个条目）
INSERT INTO
        params (key, value)
VALUES
        ('sample_limit', '512');

-- 缓存占比达到该比例且文件数不少于下限 → 判定可安全清理
INSERT INTO
        params (key, value)
VALUES
        ('cache_heavy_ratio', '0.8');

INSERT INTO
        params (key, value)
VALUES
        ('cache_heavy_min_files', '8');