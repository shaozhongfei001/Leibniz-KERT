"""对公经营分析 DuckDB 存储（CCRM-BA 落地 · 基础设施层）。

承载 CCRM 对公数据分析（Owner 指令 2026-09-22）的造数宽表，表前缀 ``cbdm_``：
- ``cbdm_cust_biz_wide``    DWD 客户×月宽表（聚合源 / 组合查询 / 下钻）
- ``cbdm_analysis_wide``    DWS 机构×维度成员×月预聚合宽表（生产预聚合形态登记）
- ``dim_org`` / ``dim_industry`` / ``dim_credit_rating`` / ``cfg_metric_banding``
  维度与分段阈值配置

设计口径：
- DuckDB 为 KERT_OPEN_SOURCE_TECH_STACK_V1.0 既定选型（docs/architecture/，§存储）。
- 库文件**不入库**：仓库只保留 ``examples/bank-front-analytics/seed/`` 造数 CSV 与
  ``scripts/build_analytics_duckdb.py`` 构建脚本；库文件由脚本在工作区/部署路径生成。
- 分析查询统一走 DWD 单一聚合路径（GROUP BY 行轴 + 期间对比在应用层合成），
  保证 mom/ytd 口径唯一；DWS 表作为生产预聚合层登记保留。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

_log = logging.getLogger(__name__)

#: 造数 CSV 标准目录（仓库内，作为构建输入）。
DEFAULT_SEED_DIR = Path(__file__).resolve().parents[3] / "examples" / "bank-front-analytics" / "seed"

_DDL = """
CREATE TABLE IF NOT EXISTS dim_org (
    org_id      VARCHAR NOT NULL,
    org_name    VARCHAR NOT NULL,
    parent_id   VARCHAR,
    org_level   INTEGER,
    org_path    VARCHAR NOT NULL,
    PRIMARY KEY (org_id)
);
CREATE TABLE IF NOT EXISTS dim_industry (
    industry_code   VARCHAR NOT NULL,
    industry_name   VARCHAR NOT NULL,
    parent_code     VARCHAR,
    PRIMARY KEY (industry_code)
);
CREATE TABLE IF NOT EXISTS dim_credit_rating (
    rating      VARCHAR NOT NULL,
    sort_no     INTEGER,
    PRIMARY KEY (rating)
);
CREATE TABLE IF NOT EXISTS cfg_metric_banding (
    band_type       VARCHAR NOT NULL,
    band_name       VARCHAR NOT NULL,
    lower_value     DOUBLE,
    upper_value     DOUBLE,
    upper_inclusive INTEGER,
    eff_date        VARCHAR,
    PRIMARY KEY (band_type, band_name, eff_date)
);
CREATE TABLE IF NOT EXISTS cfg_analytics_param (
    param_key   VARCHAR NOT NULL,
    param_value VARCHAR NOT NULL,
    unit        VARCHAR,
    remark      VARCHAR,
    eff_date    VARCHAR,
    PRIMARY KEY (param_key, eff_date)
);
CREATE TABLE IF NOT EXISTS cbdm_cust_biz_wide (
    stat_month      VARCHAR NOT NULL,
    cust_id         VARCHAR NOT NULL,
    cust_name       VARCHAR NOT NULL,
    org_id          VARCHAR NOT NULL,
    industry_code   VARCHAR,
    credit_rating   VARCHAR,
    ent_scale       VARCHAR,
    cust_type       VARCHAR,
    cust_category   VARCHAR,
    is_key_cust_hq      INTEGER,
    is_key_cust_branch  INTEGER,
    is_strategy_cust    INTEGER,
    is_sme              INTEGER,
    cust_manager_id VARCHAR,
    acct_cnt        INTEGER,
    basic_acct_flag INTEGER,
    acct_opened_mtd INTEGER,
    acct_closed_mtd INTEGER,
    acct_closed_bal DOUBLE,
    inactive_flag   INTEGER,
    cust_opened_mtd INTEGER,
    cust_closed_mtd INTEGER,
    product_cnt     INTEGER,
    dep_bal         DOUBLE,
    dep_avg_day     DOUBLE,
    dep_demand_bal  DOUBLE,
    dep_time_bal    DOUBLE,
    dep_margin_bal  DOUBLE,
    dep_due_mtd     DOUBLE,
    dep_due_next    DOUBLE,
    loan_bal        DOUBLE,
    loan_avg_day    DOUBLE,
    loan_disb_mtd   DOUBLE,
    loan_due_mtd    DOUBLE,
    loan_cls_normal      DOUBLE,
    loan_cls_special     DOUBLE,
    loan_cls_substandard DOUBLE,
    loan_cls_doubtful    DOUBLE,
    loan_cls_loss        DOUBLE,
    sett_debit_amt  DOUBLE,
    sett_credit_amt DOUBLE,
    sett_cnt_year   INTEGER,
    fee_settle      DOUBLE,
    fee_guarantee   DOUBLE,
    fee_commission  DOUBLE,
    fee_custody     DOUBLE,
    fee_consult     DOUBLE,
    fee_agency      DOUBLE,
    fee_debit_card  DOUBLE,
    fee_credit_card DOUBLE,
    fee_ebank       DOUBLE,
    fee_factoring   DOUBLE,
    fee_other       DOUBLE,
    profit_dep      DOUBLE,
    profit_loan     DOUBLE,
    profit_fee      DOUBLE,
    PRIMARY KEY (stat_month, cust_id)
);
CREATE TABLE IF NOT EXISTS cbdm_analysis_wide (
    stat_month  VARCHAR NOT NULL,
    org_id      VARCHAR NOT NULL,
    dim_type    VARCHAR NOT NULL,
    dim_value   VARCHAR NOT NULL,
    PRIMARY KEY (stat_month, org_id, dim_type, dim_value)
);
CREATE INDEX IF NOT EXISTS idx_cbo_org ON cbdm_cust_biz_wide (org_id, stat_month);
CREATE INDEX IF NOT EXISTS idx_cbo_ind ON cbdm_cust_biz_wide (industry_code, stat_month);
"""

#: 各造数表的列类型声明（read_csv columns 显式指定，避免类型推断漂移；
#: DuckDB 的 ``CAST(x AS T) x`` 别名与源列同名会触发 BinderException）。
_SEED_SPECS: dict[str, dict[str, str]] = {
    "dim_org": {"org_id": "VARCHAR", "org_name": "VARCHAR", "parent_id": "VARCHAR",
                "org_level": "INTEGER", "org_path": "VARCHAR"},
    "dim_industry": {"industry_code": "VARCHAR", "industry_name": "VARCHAR",
                     "parent_code": "VARCHAR"},
    "dim_credit_rating": {"rating": "VARCHAR", "sort_no": "INTEGER"},
    "cfg_metric_banding": {"band_type": "VARCHAR", "band_name": "VARCHAR",
                           "lower_value": "DOUBLE", "upper_value": "DOUBLE",
                           "upper_inclusive": "INTEGER", "eff_date": "VARCHAR"},
    "cfg_analytics_param": {"param_key": "VARCHAR", "param_value": "VARCHAR",
                            "unit": "VARCHAR", "remark": "VARCHAR",
                            "eff_date": "VARCHAR"},
    "cbdm_cust_biz_wide": {
        "stat_month": "VARCHAR", "cust_id": "VARCHAR", "cust_name": "VARCHAR",
        "org_id": "VARCHAR", "industry_code": "VARCHAR", "credit_rating": "VARCHAR",
        "ent_scale": "VARCHAR", "cust_type": "VARCHAR", "cust_category": "VARCHAR",
        "is_key_cust_hq": "INTEGER", "is_key_cust_branch": "INTEGER",
        "is_strategy_cust": "INTEGER", "is_sme": "INTEGER",
        "cust_manager_id": "VARCHAR",
        "acct_cnt": "INTEGER", "basic_acct_flag": "INTEGER",
        "acct_opened_mtd": "INTEGER", "acct_closed_mtd": "INTEGER",
        "acct_closed_bal": "DOUBLE", "inactive_flag": "INTEGER",
        "cust_opened_mtd": "INTEGER", "cust_closed_mtd": "INTEGER",
        "product_cnt": "INTEGER",
        "dep_bal": "DOUBLE", "dep_avg_day": "DOUBLE", "dep_demand_bal": "DOUBLE",
        "dep_time_bal": "DOUBLE", "dep_margin_bal": "DOUBLE", "dep_due_mtd": "DOUBLE",
        "dep_due_next": "DOUBLE",
        "loan_bal": "DOUBLE", "loan_avg_day": "DOUBLE", "loan_disb_mtd": "DOUBLE",
        "loan_due_mtd": "DOUBLE", "loan_cls_normal": "DOUBLE",
        "loan_cls_special": "DOUBLE", "loan_cls_substandard": "DOUBLE",
        "loan_cls_doubtful": "DOUBLE", "loan_cls_loss": "DOUBLE",
        "sett_debit_amt": "DOUBLE", "sett_credit_amt": "DOUBLE",
        "sett_cnt_year": "INTEGER",
        "fee_settle": "DOUBLE", "fee_guarantee": "DOUBLE", "fee_commission": "DOUBLE",
        "fee_custody": "DOUBLE", "fee_consult": "DOUBLE", "fee_agency": "DOUBLE",
        "fee_debit_card": "DOUBLE", "fee_credit_card": "DOUBLE", "fee_ebank": "DOUBLE",
        "fee_factoring": "DOUBLE", "fee_other": "DOUBLE",
        "profit_dep": "DOUBLE", "profit_loan": "DOUBLE", "profit_fee": "DOUBLE",
    },
}


class AnalyticsDuckDb:
    """对公经营分析 DuckDB 只读存储（查询侧）+ 构建侧入口。"""

    def __init__(self, path: Path | str, read_only: bool = True):
        import duckdb  # 局部导入：duckdb 仅分析能力需要，不拖累核心启动路径

        self.path = Path(path)
        self._read_only = bool(read_only)
        if self._read_only and not self.path.is_file():
            raise FileNotFoundError(f"分析库不存在: {self.path}")
        # DuckDB 单连接**非线程安全**：FastAPI 将同步端点放入线程池，
        # 浏览器并发拉取 dimensions/orgs/periods/metrics 时互相覆盖游标，
        # 表现为间歇性 KeyError / 400（2026-09-22 线上复现）。查询串行化修复。
        self._lock = threading.Lock()
        self._con = duckdb.connect(str(self.path), read_only=self._read_only)

    # ---------------- 查询 ----------------

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        with self._lock:
            cur = self._con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def one(self, sql: str, params: list | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: list | None = None):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def close(self) -> None:
        self._con.close()

    # ---------------- 构建 ----------------

    def rebuild(self, seed_dir: Path | str) -> dict[str, int]:
        """从造数 CSV 重建全部 cbdm_* / dim_* 表（构建侧，read_only=False）。"""
        if self._read_only:
            raise RuntimeError("rebuild 需要 read_only=False")
        seed = Path(seed_dir)
        missing = [f for f in _SEED_SPECS if not (seed / f"{f}.csv").is_file()]
        if missing:
            raise FileNotFoundError(f"种子 CSV 缺失: {missing}（seed_dir={seed}）")
        self._con.execute("BEGIN TRANSACTION")
        try:
            for name in _SEED_SPECS:
                self._con.execute(f"DROP TABLE IF EXISTS {name}")
            self._con.execute(_DDL)
            counts: dict[str, int] = {}
            for name, spec in _SEED_SPECS.items():
                csv = str(seed / f"{name}.csv")
                cols_sql = ", ".join(f"'{c}': '{t}'" for c, t in spec.items())
                self._con.execute(
                    f"INSERT INTO {name} SELECT * FROM read_csv(?, header=true, "
                    f"columns={{{cols_sql}}})", [csv])
                counts[name] = self.scalar(f"SELECT COUNT(*) FROM {name}")
            # DWS 宽表列多且本层不查询，仅登记行键 + 全量原样导入其余列。
            dws_csv = str(seed / "cbdm_analysis_wide.csv")
            self._con.execute(
                "CREATE OR REPLACE TABLE cbdm_analysis_wide AS "
                "SELECT * FROM read_csv_auto(?, header=true)", [dws_csv])
            counts["cbdm_analysis_wide"] = self.scalar(
                "SELECT COUNT(*) FROM cbdm_analysis_wide")
            self._con.execute("COMMIT")
            _log.info("分析库重建完成：%s -> %s（%s）", seed, self.path, counts)
            return counts
        except Exception:
            self._con.execute("ROLLBACK")
            raise
