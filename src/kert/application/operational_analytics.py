"""对公经营数据分析服务（CCRM-BA 落地 · KERT 应用层）。

数据源：DuckDB 造数宽表（cbdm_cust_biz_wide，见 infrastructure/analytics_store.py）。
本模块是 10 个分析屏（CCRM 原型遍历结论）的唯一口径来源：

- 经营指标分析（4 屏，行=机构）：operating-customer / operating-overview /
  operating-profit / operating-risk
- 细分客群分析（2 屏，行=维度成员）：segment-distribution / segment-business
- 组合查询（1 屏，客户级圈选）：combo-query
- 指标监视器（3 屏，行=维度成员）：monitor-balance / monitor-ldr / monitor-npl

口径纪律（CCRM-BA-REQ-001 §3.3 指标字典）：
- 环比（Mom）= 当期 / 上一期 − 1；比年初（Ytd）= 当期 / 当年首期 − 1。
- 不良贷款余额 = 次级 + 可疑 + 损失；不良率 = 不良 / 贷款余额；存贷比 = 贷款 / 存款。
- 收入总额口径（造数近似）= 11 类中间业务收入 + 存款利润贡献 + 贷款利润贡献。
- ROA 口径（造数近似）= 年化综合利润 / (存款余额+贷款余额)；ROE = ROA × 12.5。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.errors import UsageError
from ..infrastructure.analytics_store import AnalyticsDuckDb

# --------------------------------------------------------------------------- #
# 维度定义（与原型「分布维度」下拉一致）
# --------------------------------------------------------------------------- #

DIMENSIONS: list[tuple[str, str]] = [
    ("INDUSTRY", "行业"),
    ("CREDIT_RATING", "信用等级"),
    ("ENT_SCALE", "企业规模"),
    ("CUST_TYPE", "客户类型"),
    ("CUST_CATEGORY", "客户类别"),
    ("DEP_BAND", "存款余额分段"),
    ("LOAN_BAND", "贷款余额分段"),
    ("SETTLE_BAND", "结算量分段"),
    ("PROFIT_BAND", "利润贡献分段"),
    ("KEY_CUST", "重点客户"),
    ("SME", "中小企业"),
]
DIM_LABELS = dict(DIMENSIONS)

# 监视器允许的维度（原文口径：行业 / 客户类型 / 客户类别）
MONITOR_DIMS = ("INDUSTRY", "CUST_TYPE", "CUST_CATEGORY")
# 细分客户业务 tab
BIZ_TYPES = ("DEPOSIT", "LOAN", "FEE", "SETTLEMENT")

#: SUM 口径指标（SQL 表达式，别名 = 指标 key）。
_AGG: dict[str, str] = {
    "custCnt": "COUNT(*)",
    "custCntNew": "SUM(w.cust_opened_mtd)",
    # custCntInactive 不在本表：口径 = 连续 inactive_months 期结算为 0，
    # 由 _inactive_by_member() 按 N 期窗口计算后在 metrics() 覆盖注入。
    "basicCnt": "SUM(w.basic_acct_flag)",
    "acctCnt": "SUM(w.acct_cnt)",
    "acctClosedCnt": "SUM(w.acct_closed_mtd)",
    "acctClosedBal": "SUM(w.acct_closed_bal)",
    "productSum": "SUM(w.product_cnt)",
    "depBal": "SUM(w.dep_bal)",
    "depAvgDay": "SUM(w.dep_avg_day)",
    "depDemandBal": "SUM(w.dep_demand_bal)",
    "depTimeBal": "SUM(w.dep_time_bal)",
    "depMarginBal": "SUM(w.dep_margin_bal)",
    "depDueMtd": "SUM(w.dep_due_mtd)",
    "depDueNext": "SUM(w.dep_due_next)",
    "loanBal": "SUM(w.loan_bal)",
    "loanAvgDay": "SUM(w.loan_avg_day)",
    "loanDisbMtd": "SUM(w.loan_disb_mtd)",
    "loanDueMtd": "SUM(w.loan_due_mtd)",
    "loanClsSubstandard": "SUM(w.loan_cls_substandard)",
    "loanClsDoubtful": "SUM(w.loan_cls_doubtful)",
    "loanClsLoss": "SUM(w.loan_cls_loss)",
    "settDebitAmt": "SUM(w.sett_debit_amt)",
    "settCreditAmt": "SUM(w.sett_credit_amt)",
    "settTotalAmt": "SUM(w.sett_debit_amt + w.sett_credit_amt)",
    "settNetAmt": "SUM(ABS(w.sett_debit_amt - w.sett_credit_amt))",
    "feeSettle": "SUM(w.fee_settle)", "feeGuarantee": "SUM(w.fee_guarantee)",
    "feeCommission": "SUM(w.fee_commission)", "feeCustody": "SUM(w.fee_custody)",
    "feeConsult": "SUM(w.fee_consult)", "feeAgency": "SUM(w.fee_agency)",
    "feeDebitCard": "SUM(w.fee_debit_card)", "feeCreditCard": "SUM(w.fee_credit_card)",
    "feeEbank": "SUM(w.fee_ebank)", "feeFactoring": "SUM(w.fee_factoring)",
    "feeOther": "SUM(w.fee_other)",
    "profitDep": "SUM(w.profit_dep)", "profitLoan": "SUM(w.profit_loan)",
    "profitFee": "SUM(w.profit_fee)",
    "profitTotal": "SUM(w.profit_dep + w.profit_loan + w.profit_fee)",
    "nplBal": "SUM(w.loan_cls_substandard + w.loan_cls_doubtful + w.loan_cls_loss)",
}
_FEE_SUM = ("(w.fee_settle + w.fee_guarantee + w.fee_commission + w.fee_custody "
            "+ w.fee_consult + w.fee_agency + w.fee_debit_card + w.fee_credit_card "
            "+ w.fee_ebank + w.fee_factoring + w.fee_other)")
_AGG["feeTotal"] = f"SUM({_FEE_SUM})"
_INCOME = f"({_FEE_SUM} + w.profit_dep + w.profit_loan)"
_AGG["incomeTotal"] = f"SUM({_INCOME})"
_AGG["incomeSme"] = f"SUM(CASE WHEN w.is_sme = 1 THEN {_INCOME} ELSE 0 END)"
_AGG["incomeNonSme"] = f"SUM(CASE WHEN w.is_sme = 0 THEN {_INCOME} ELSE 0 END)"
_AGG["incomeNewSme"] = (
    f"SUM(CASE WHEN w.is_sme = 1 AND w.cust_opened_mtd = 1 THEN {_INCOME} ELSE 0 END)")
_AGG["incomeNewNonSme"] = (
    f"SUM(CASE WHEN w.is_sme = 0 AND w.cust_opened_mtd = 1 THEN {_INCOME} ELSE 0 END)")


@dataclass
class ScreenSpec:
    screen_id: str
    label: str
    group: str                      # operating / segment / monitor
    row_axis: str                   # ORG（行=机构） / DIM（行=维度成员）
    metrics: list[str]             # 输出的值指标（含派生）
    shares: list[str] = field(default_factory=list)   # 额外输出 <key>Share
    dims: tuple[str, ...] = ()      # 允许的分布维度（DIM 屏）
    biz_types: tuple[str, ...] = ()  # segment-business 专属


#: 10 屏注册表（CCRM 原型「分析工具」菜单遍历结论，V1.0 落地）。
SCREENS: dict[str, ScreenSpec] = {
    "operating-customer": ScreenSpec(
        "operating-customer", "客户指标分析", "operating", "ORG",
        ["custCnt", "custCntNew", "incomeTotal", "incomeSme", "incomeNonSme",
         "acctCnt", "acctClosedCnt", "acctClosedBal", "custCntInactive"],
        dims=tuple(dict(DIMENSIONS))),
    "operating-overview": ScreenSpec(
        "operating-overview", "业务概况分析", "operating", "ORG",
        ["depBal", "loanBal", "feeTotal"],
        dims=tuple(dict(DIMENSIONS))),
    "operating-profit": ScreenSpec(
        "operating-profit", "利润贡献分析", "operating", "ORG",
        ["profitTotal", "profitDep", "profitLoan", "profitFee"],
        shares=["profitTotal", "profitDep", "profitLoan", "profitFee"],
        dims=tuple(dict(DIMENSIONS))),
    "operating-risk": ScreenSpec(
        "operating-risk", "风险指标分析", "operating", "ORG",
        ["roa", "roe", "nplRatio", "nplBal"],
        dims=tuple(dict(DIMENSIONS))),
    "segment-distribution": ScreenSpec(
        "segment-distribution", "客户分布特征分析", "segment", "DIM",
        ["custCnt", "avgDep", "avgLoan", "avgSett", "avgProfit", "avgProd",
         "basicCnt", "acctCnt"],
        shares=["custCnt"],
        dims=tuple(dict(DIMENSIONS))),
    "segment-business": ScreenSpec(
        "segment-business", "细分客户业务分析", "segment", "DIM",
        [],  # 列由 bizType 决定（_BIZ_METRICS）
        dims=("INDUSTRY", "CREDIT_RATING", "ENT_SCALE"),
        biz_types=BIZ_TYPES),
    "monitor-balance": ScreenSpec(
        "monitor-balance", "业务增减变化监控", "monitor", "DIM",
        ["depBal", "loanBal", "loanDisbMtd", "settTotalAmt"],
        dims=MONITOR_DIMS),
    "monitor-ldr": ScreenSpec(
        "monitor-ldr", "存贷比变化监控", "monitor", "DIM",
        ["ldr", "depBal", "loanBal"],
        dims=MONITOR_DIMS),
    "monitor-npl": ScreenSpec(
        "monitor-npl", "不良贷款分布变化监控", "monitor", "DIM",
        ["nplBal", "nplRatio"],
        shares=["nplBal"],
        dims=MONITOR_DIMS),
}

_BIZ_METRICS: dict[str, list[str]] = {
    "DEPOSIT": ["depBal", "depAvgDay", "depDemandBal", "depTimeBal",
                "depMarginBal", "depDueMtd", "depDueNext"],
    "LOAN": ["loanBal", "loanAvgDay", "loanDisbMtd", "loanDueMtd",
             "loanClsSubstandard", "loanClsDoubtful", "loanClsLoss"],
    "FEE": ["feeSettle", "feeGuarantee", "feeCommission", "feeCustody",
            "feeConsult", "feeAgency", "feeDebitCard", "feeCreditCard",
            "feeEbank", "feeFactoring", "feeOther", "feeTotal"],
    "SETTLEMENT": ["settDebitAmt", "settCreditAmt", "settTotalAmt", "settNetAmt"],
}
_BIZ_METRIC_SET = set().union(*_BIZ_METRICS.values())

#: 派生指标（非 SUM）：值 = f(sums)；mom/ytd 先按期间算值再对比。
#: 口径参数化（Owner 决策 2026-09-22，见 _DEFAULT_PARAMS / cfg_analytics_param）。
_DERIVED_KEYS = ("ldr", "nplRatio", "roa", "roe", "avgDep", "avgLoan",
                 "avgSett", "avgProfit", "avgProd")

#: 分析参数默认值（cfg_analytics_param 缺项/非法值时兜底）。
#: 真实口径接入点：profit_source=FTP（要求数据表出现 FTP 利润列，缺失即 fail-closed）。
_DEFAULT_PARAMS: dict[str, object] = {
    "alert_threshold": 0.15,        # 监视器环比告警阈值（±，原型口径）
    "roe_leverage": 12.5,           # ROE = ROA × 杠杆系数（真实资本口径接入前为近似）
    "roa_annualize_months": 12,     # ROA 年化月数
    "inactive_months": 3,           # 不动户判定月数 N
    "profit_source": "DERIVED",     # DERIVED=造数近似 / FTP=真实 FTP 利润列
}
_FTP_PROFIT_COLUMNS = ("profit_dep_ftp", "profit_loan_ftp", "profit_fee_ftp")

#: 组合查询数值条件的指标白名单（列名映射；fail-closed，防注入）。
COMBO_METRIC_COLUMNS: dict[str, str] = {
    "depBal": "dep_bal",
    "depAvgDay": "dep_avg_day",
    "loanBal": "loan_bal",
    "loanAvgDay": "loan_avg_day",
    "settAmtYear": "sett_year",
    "settCntYear": "sett_cnt_year",
    "feeYear": "fee_year",
    "profitTotalYear": "profit_year",
    "ldr": "ldr",
}
COMBO_OPERATORS = {"=", ">", ">=", "<", "<="}

#: 分段维度的默认阈值（cfg_metric_banding 缺失时兜底；单位万元）。
_DEFAULT_BANDS: dict[str, list[dict]] = {
    "DEP_BAND": [{"band_name": "年日均存款余额1亿（含）以上", "lower_value": 10000},
                 {"band_name": "5000万（含）-1亿", "lower_value": 5000,
                  "upper_value": 10000},
                 {"band_name": "1000万（含）-5000万", "lower_value": 1000,
                  "upper_value": 5000},
                 {"band_name": "1000万以下", "upper_value": 1000}],
    "LOAN_BAND": [{"band_name": "贷款余额5亿（含）以上", "lower_value": 50000},
                  {"band_name": "1亿（含）-5亿", "lower_value": 10000,
                   "upper_value": 50000},
                  {"band_name": "1亿以下", "upper_value": 10000}],
    "SETTLE_BAND": [{"band_name": "结算量1亿（含）以上", "lower_value": 10000},
                    {"band_name": "结算量1亿以下", "upper_value": 10000}],
    "PROFIT_BAND": [{"band_name": "利润贡献100万（含）以上", "lower_value": 100},
                    {"band_name": "利润贡献100万以下", "upper_value": 100}],
}


def _safe_div(a, b):
    if a is None or not b:
        return None
    return a / b


def _prev_period(period: str) -> str | None:
    y, m = int(period[:4]), int(period[4:6])
    if m == 1:
        return None
    return f"{y}{m - 1:02d}"


def _ratio(cur, base) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return cur / base - 1


def _is_period(period: str) -> bool:
    return (isinstance(period, str) and len(period) == 6
            and period.isdigit() and 1 <= int(period[4:6]) <= 12)


class OperationalAnalyticsService:
    """对公经营分析服务：维度元数据 + 10 屏指标聚合 + 趋势 + 组合查询。"""

    def __init__(self, store: AnalyticsDuckDb):
        self._store = store
        self._bands = self._load_bandings()
        self._params = self._load_params()
        self._ftp_cols: tuple[str, ...] | None = None

    # ---------------- 分析参数（口径可配置）----------------

    def params(self) -> dict:
        """当前生效的分析参数（供端点/技能/评审核对口径）。"""
        return dict(self._params)

    def _load_params(self) -> dict:
        params = dict(_DEFAULT_PARAMS)
        try:
            rows = self._store.query(
                "SELECT param_key, param_value FROM cfg_analytics_param")
        except Exception:  # noqa: BLE001 — 配置表缺失时全量兜底默认值
            return params
        for r in rows:
            key, raw = str(r.get("param_key")), r.get("param_value")
            if key not in params:
                continue
            default = params[key]
            try:
                params[key] = str(raw) if isinstance(default, str) else float(raw)
            except (TypeError, ValueError):
                continue  # 非法值不覆盖默认（保守，不静默放大口径）
        return params

    def _profit_total(self, sums: dict):
        """综合利润口径：DERIVED（造数）= 存贷贡献+中收；FTP = 真实 FTP 利润列。"""
        if str(self._params.get("profit_source", "DERIVED")).upper() == "FTP":
            return sum((sums.get(c) or 0) for c in self._ftp_columns())
        return sums.get("profitTotal")

    def _ftp_columns(self) -> tuple[str, ...]:
        """FTP 利润列（列名约定 profit_{dep|loan|fee}_ftp）；缺失即 fail-closed。"""
        if self._ftp_cols is not None:
            return self._ftp_cols
        rows = self._store.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'cbdm_cust_biz_wide'")
        names = {str(r["column_name"]) for r in rows}
        missing = [c for c in _FTP_PROFIT_COLUMNS if c not in names]
        if missing:
            raise UsageError(
                "profit_source=FTP 但数据表缺少 FTP 利润列 "
                f"{missing}（fail-closed；需先接入真实 FTP 口径）")
        self._ftp_cols = _FTP_PROFIT_COLUMNS
        return self._ftp_cols

    def _derive(self, sums: dict) -> dict:
        """派生指标（参数化口径：年化月数 / 杠杆系数 / 利润来源）。

        空聚合（成员/期间无数据）⇒ 全部派生值为 ``None``，**不得**抛 TypeError
        （QA FAIL-2026-09-22-AN0-QA-02：`_derive({})` 曾因 profit=None 抛 500）。
        """
        if not sums:
            return dict.fromkeys(_DERIVED_KEYS)
        months = float(self._params["roa_annualize_months"])
        leverage = float(self._params["roe_leverage"])
        profit = self._profit_total(sums) or 0
        assets = max((sums.get("depBal") or 0) + (sums.get("loanBal") or 0), 1e-9)
        roa = profit * months / assets
        return {
            "ldr": _safe_div(sums.get("loanBal"), sums.get("depBal")),
            "nplRatio": _safe_div(sums.get("nplBal"), sums.get("loanBal")),
            "roa": roa,
            "roe": roa * leverage,
            "avgDep": _safe_div(sums.get("depBal"), sums.get("custCnt")),
            "avgLoan": _safe_div(sums.get("loanBal"), sums.get("custCnt")),
            "avgSett": _safe_div(sums.get("settTotalAmt"), sums.get("custCnt")),
            "avgProfit": _safe_div(profit, sums.get("custCnt")),
            "avgProd": _safe_div(sums.get("productSum"), sums.get("custCnt")),
        }

    def _inactive_by_member(self, row_axis: str, org_id: str, period: str,
                            dim_values: list[str] | None) -> dict[str, int]:
        """不动户（参数化口径）：**连续 ``inactive_months`` 期结算发生额为 0** 的客户数。

        QA FAIL-2026-09-22-AN0-QA-04：此前 `inactive_months` 仅声明未接线，
        指标直用造数标志位 `w.inactive_flag`；现改为按 N 期窗口从月度事实计算，
        参数一变口径即变（可被门禁/变异复验捕获）。
        """
        n = max(1, int(float(self._params["inactive_months"])))
        periods = self.periods()
        if period not in periods:
            return {}
        end = periods.index(period)
        window = periods[max(0, end - n + 1): end + 1]
        dim_expr = self._dim_expr(row_axis)
        where = ["w.stat_month BETWEEN ? AND ?",
                 "w.org_id IN (SELECT org_id FROM dim_org WHERE org_path LIKE ?)"]
        params: list = [window[0], window[-1], self._org_path(org_id) + "%"]
        if dim_values and row_axis != "ORG":
            marks = ",".join("?" * len(dim_values))
            where.append(f"({dim_expr}) IN ({marks})")
            params.extend(str(v) for v in dim_values)
        sql = (f"WITH win AS (SELECT w.cust_id AS cust_id, ({dim_expr}) AS dim_value, "
               "SUM(w.sett_debit_amt + w.sett_credit_amt) AS sett_sum "
               "FROM cbdm_cust_biz_wide w "
               "LEFT JOIN dim_industry di ON w.industry_code = di.industry_code "
               + ("JOIN dim_org o ON w.org_id = o.org_id " if row_axis == "ORG" else "")
               + "WHERE " + " AND ".join(where)
               + " GROUP BY 1, 2) "
               "SELECT dim_value, COUNT(DISTINCT CASE WHEN sett_sum = 0 THEN cust_id END) "
               "AS inactive_cnt FROM win GROUP BY 1")
        return {r["dim_value"]: int(r["inactive_cnt"] or 0)
                for r in self._store.query(sql, params)}

    # ---------------- 维度表达式（分段维度需实例化阈值） ----------------

    def _dim_expr(self, dim: str) -> str:
        if dim == "INDUSTRY":
            return "di.industry_name"
        if dim == "CREDIT_RATING":
            return "w.credit_rating"
        if dim == "ENT_SCALE":
            return "w.ent_scale"
        if dim == "CUST_TYPE":
            return "w.cust_type"
        if dim == "CUST_CATEGORY":
            return "w.cust_category"
        if dim == "KEY_CUST":
            return ("CASE WHEN w.is_key_cust_hq = 1 THEN '总行级重点客户' "
                    "WHEN w.is_key_cust_branch = 1 THEN '分行级重点客户' "
                    "ELSE '非重点客户' END")
        if dim == "SME":
            return "CASE WHEN w.is_sme = 1 THEN '小企业' ELSE '非小企业' END"
        if dim == "ORG":
            return "o.org_name"
        if dim in ("DEP_BAND", "LOAN_BAND", "SETTLE_BAND", "PROFIT_BAND"):
            value_expr = {
                "DEP_BAND": "w.dep_avg_day",
                "LOAN_BAND": "w.loan_bal",
                "SETTLE_BAND": "(w.sett_debit_amt + w.sett_credit_amt)",
                "PROFIT_BAND": "(w.profit_dep + w.profit_loan + w.profit_fee)",
            }[dim]
            return self._band_expr(dim, value_expr)
        raise UsageError(f"dim 非法: {dim}")

    def _band_expr(self, band_type: str, value_expr: str) -> str:
        bands = self._bands.get(band_type) or _DEFAULT_BANDS[band_type]
        parts = []
        for b in bands:
            conds = []
            if b.get("lower_value") is not None:
                conds.append(f"{value_expr} >= {float(b['lower_value'])}")
            if b.get("upper_value") is not None:
                conds.append(f"{value_expr} < {float(b['upper_value'])}")
            if conds:
                parts.append(f"WHEN {' AND '.join(conds)} THEN '{b['band_name']}'")
        if not parts:
            return "'其他'"
        return "CASE " + " ".join(parts) + " ELSE '其他' END"

    def _load_bandings(self) -> dict[str, list[dict]]:
        bands: dict[str, list[dict]] = {}
        try:
            for r in self._store.query(
                    "SELECT band_type, band_name, lower_value, upper_value "
                    "FROM cfg_metric_banding ORDER BY band_type, "
                    "COALESCE(lower_value, -1e18)"):
                bands.setdefault(r["band_type"], []).append(r)
        except Exception:  # noqa: BLE001 — 配置缺失时退回内置阈值
            pass
        return bands

    # ---------------- 元数据 ----------------

    def dimensions(self) -> list[dict]:
        out = []
        for dim, label in DIMENSIONS:
            rows = self._store.query(
                f"SELECT DISTINCT {self._dim_expr(dim)} AS dim_value "
                "FROM cbdm_cust_biz_wide w "
                "LEFT JOIN dim_industry di ON w.industry_code = di.industry_code "
                + ("JOIN dim_org o ON w.org_id = o.org_id " if dim == "ORG" else "")
                + "ORDER BY 1")
            out.append({"dimType": dim, "label": label,
                        "members": [r["dim_value"] for r in rows]})
        return out

    def orgs(self) -> list[dict]:
        return self._store.query(
            "SELECT org_id AS orgId, org_name AS orgName, org_level AS orgLevel, "
            "org_path AS orgPath FROM dim_org ORDER BY org_level, org_id")

    def periods(self) -> list[str]:
        rows = self._store.query(
            "SELECT DISTINCT stat_month FROM cbdm_cust_biz_wide ORDER BY 1")
        return [r["stat_month"] for r in rows]

    def screen_catalog(self) -> list[dict]:
        out = []
        for spec in SCREENS.values():
            if spec.screen_id == "segment-business":
                metrics = {bt: _BIZ_METRICS[bt] for bt in spec.biz_types}
            else:
                metrics = list(spec.metrics)
            out.append({
                "screenId": spec.screen_id, "label": spec.label,
                "group": spec.group, "rowAxis": spec.row_axis,
                "dims": list(spec.dims), "metrics": metrics,
                "bizTypes": list(spec.biz_types),
            })
        return out

    # ---------------- 指标聚合 ----------------

    def metrics(self, screen: str, dim: str, org_id: str, period: str,
                dim_values: list[str] | None = None,
                biz_type: str | None = None) -> dict:
        spec = self._screen(screen)
        if spec.screen_id == "segment-business":
            biz_type = (biz_type or "DEPOSIT").upper()
            if biz_type not in spec.biz_types:
                raise UsageError(
                    f"bizType 非法: {biz_type}（允许 {list(spec.biz_types)}）")
        else:
            biz_type = None
        self._validate_dim(spec, dim)
        if not _is_period(period):
            raise UsageError(f"period 非法: {period}（应为 YYYYMM）")

        row_axis = "ORG" if spec.row_axis == "ORG" else dim
        frames: dict[str, dict[str, dict]] = {}
        for tag, p in (("cur", period), ("prev", _prev_period(period)),
                       ("y0", f"{period[:4]}01")):
            if p is None:
                continue
            frames[tag] = self._aggregate(row_axis, org_id, p, dim_values)

        cur_frame = frames.get("cur", {})
        metric_keys = self._metric_keys(spec, biz_type)
        # 不动户（参数化 N 期窗口）覆盖注入：仅当本屏需要该指标时才计算
        if "custCntInactive" in metric_keys:
            for tag, p in (("cur", period), ("prev", _prev_period(period)),
                           ("y0", f"{period[:4]}01")):
                if p is None or tag not in frames:
                    continue
                for member, cnt in self._inactive_by_member(
                        row_axis, org_id, p, dim_values).items():
                    if member in frames[tag]:
                        frames[tag][member]["custCntInactive"] = cnt
        primary = metric_keys[0]
        order = sorted(cur_frame.keys(),
                       key=lambda m: -(cur_frame[m].get(primary) or 0))
        totals = self._totals(cur_frame, metric_keys)

        rows = []
        for member in order:
            cur = cur_frame.get(member, {})
            prev = frames.get("prev", {}).get(member, {})
            y0 = frames.get("y0", {}).get(member, {})
            row: dict = {"dimValue": member}
            for key in metric_keys:
                v = cur.get(key)
                row[key] = None if v is None else round(v, 4)
                mom = _ratio(v, prev.get(key))
                ytd = _ratio(v, y0.get(key))
                row[key + "Mom"] = None if mom is None else round(mom, 4)
                row[key + "Ytd"] = None if ytd is None else round(ytd, 4)
            for key in spec.shares:
                tot = totals.get(key)
                row[key + "Share"] = (None if not tot
                                      else round((cur.get(key) or 0) / tot, 4))
            rows.append(row)

        result = {
            "screen": screen, "screenLabel": spec.label,
            "bizType": biz_type, "dim": row_axis,
            "orgId": org_id, "period": period,
            "rowAxis": spec.row_axis, "rows": rows,
            "meta": {"rowCount": len(rows), "unit": "万元/户/%",
                     "momBasis": "对上一月", "ytdBasis": "对当年首月",
                     "derivedMetrics": list(_DERIVED_KEYS),
                     # 生效口径（参数化，Owner 决策 2026-09-22）
                     "params": {"alertThreshold": float(self._params["alert_threshold"]),
                                "roeLeverage": float(self._params["roe_leverage"]),
                                "roaAnnualizeMonths": float(self._params["roa_annualize_months"]),
                                "inactiveMonths": float(self._params["inactive_months"]),
                                "profitSource": str(self._params["profit_source"])},
                     # 口径说明（供评审核对，QA FAIL-2026-09-22-AN0-QA-04）
                     "inactiveBasis": "连续 inactive_months 期结算发生额为 0 的客户数"},
        }
        if spec.group == "monitor":
            result["alerts"] = self._alerts(metric_keys, rows)
        return result

    # ---------------- 趋势 ----------------

    def trend(self, screen: str, dim: str, dim_value: str, org_id: str,
              metric: str, months: int = 12) -> dict:
        spec = self._screen(screen)
        if spec.screen_id == "segment-business":
            metric_ok = metric in _BIZ_METRIC_SET
        else:
            metric_ok = metric in self._metric_keys(spec, None)
        if not metric_ok:
            raise UsageError(f"metric 非法: {metric}")
        self._validate_dim(spec, dim)
        months = max(1, min(int(months), 24))
        periods = [p for p in self.periods()][-months:]
        if not periods:
            return {"dimValue": dim_value, "metric": metric, "points": []}
        frame = self._series_agg(dim, org_id, periods, dim_value)
        points = []
        for p in periods:
            sums = frame.get(p, {})
            derived = self._derive(sums)
            value = sums.get(metric, derived.get(metric))
            points.append({"period": p,
                           "value": None if value is None else round(value, 4)})
        return {"dimValue": dim_value, "metric": metric,
                "orgId": org_id, "points": points}

    # ---------------- 组合查询 ----------------

    def combo_query(self, filters: dict | None = None,
                    page_number: int = 0, page_size: int = 20) -> dict:
        filters = filters or {}
        period = str(filters.get("period") or self.periods()[-1])
        if not _is_period(period):
            raise UsageError(f"period 非法: {period}")
        org_id = str(filters.get("orgId") or "350000")

        where: list[str] = [
            "w.stat_month BETWEEN ? AND ?",
            "w.org_id IN (SELECT org_id FROM dim_org WHERE org_path LIKE ?)",
        ]
        where_params: list = [f"{period[:4]}01", period,
                              self._org_path(org_id) + "%"]

        def _in_clause(column: str, values) -> None:
            vals = [str(v) for v in values or [] if str(v)]
            if vals:
                where.append(f"{column} IN ({','.join('?' * len(vals))})")
                where_params.extend(vals)

        _in_clause("w.credit_rating", filters.get("creditRating"))
        _in_clause("w.ent_scale", filters.get("entScale"))
        _in_clause("w.industry_code", filters.get("industryCodes"))
        _in_clause("w.cust_type", filters.get("custType"))
        _in_clause("w.cust_category", filters.get("custCategory"))
        if filters.get("custName"):
            where.append("w.cust_name LIKE ?")
            where_params.append(f"%{filters['custName']}%")
        if filters.get("custId"):
            where.append("w.cust_id = ?")
            where_params.append(str(filters["custId"]))
        flags = {"isKeyCustHq": "w.is_key_cust_hq",
                 "isKeyCustBranch": "w.is_key_cust_branch",
                 "isStrategyCust": "w.is_strategy_cust",
                 "isSme": "w.is_sme"}
        for key, col in flags.items():
            val = filters.get(key)
            if val is True:
                where.append(f"{col} = 1")
            elif val is False:
                where.append(f"{col} = 0")

        # 数值条件（HAVING，聚合后过滤；白名单 fail-closed）
        having_parts: list[str] = []
        having_params: list = []
        point_expr = {m: f"SUM(CASE WHEN w.stat_month = ? THEN {c} ELSE 0 END)"
                      for m, c in (("depBal", "w.dep_bal"),
                                   ("depAvgDay", "w.dep_avg_day"),
                                   ("loanBal", "w.loan_bal"),
                                   ("loanAvgDay", "w.loan_avg_day"))}
        year_expr = {
            "settAmtYear": "SUM(w.sett_debit_amt + w.sett_credit_amt)",
            "settCntYear": "SUM(w.sett_cnt_year)",
            "feeYear": f"SUM({_FEE_SUM})",
            "profitTotalYear": "SUM(w.profit_dep + w.profit_loan + w.profit_fee)",
            "ldr": ("(SUM(CASE WHEN w.stat_month = ? THEN w.loan_bal ELSE 0 END) "
                    "* 1.0 / NULLIF(SUM(CASE WHEN w.stat_month = ? "
                    "THEN w.dep_bal ELSE 0 END), 0))"),
        }
        for rule in filters.get("amountRules") or []:
            if not isinstance(rule, dict):
                continue
            metric = str(rule.get("metric") or "")
            op = str(rule.get("op") or "")
            value = rule.get("value")
            if metric not in COMBO_METRIC_COLUMNS:
                raise UsageError(f"amountRules.metric 非法: {metric}")
            if op not in COMBO_OPERATORS:
                raise UsageError(f"amountRules.op 非法: {op}")
            if value is None or isinstance(value, bool):
                raise UsageError("amountRules.value 非法")
            if metric in point_expr:
                having_parts.append(f"{point_expr[metric]} {op} ?")
                having_params.extend([period, float(value)])
            elif metric == "ldr":
                having_parts.append(f"{year_expr[metric]} {op} ?")
                having_params.extend([period, period, float(value)])
            else:
                having_parts.append(f"{year_expr[metric]} {op} ?")
                having_params.append(float(value))

        having_sql = (" HAVING " + " AND ".join(having_parts)) if having_parts else ""
        where_sql = " WHERE " + " AND ".join(where)
        joins = ("FROM cbdm_cust_biz_wide w "
                 "JOIN dim_org o ON w.org_id = o.org_id "
                 "LEFT JOIN dim_industry di ON w.industry_code = di.industry_code ")

        # 计数（子查询含 HAVING，与主查询同过滤口径）
        count_params = where_params + having_params
        count_rows = self._store.query(
            "SELECT COUNT(*) AS total FROM (SELECT w.cust_id " + joins
            + where_sql + " GROUP BY w.cust_id" + having_sql + ") t",
            count_params)
        total = count_rows[0]["total"] if count_rows else 0

        page_number = max(0, int(page_number))
        page_size = max(1, min(int(page_size), 200))
        select_sql = ("""
SELECT w.cust_id AS custId, MAX(w.cust_name) AS custName,
       MAX(w.org_id) AS orgId, MAX(o.org_name) AS orgName,
       MAX(w.industry_code) AS industryCode, MAX(di.industry_name) AS industry,
       MAX(w.credit_rating) AS creditRating, MAX(w.ent_scale) AS entScale,
       MAX(w.cust_type) AS custType, MAX(w.cust_category) AS custCategory,
       MAX(w.is_key_cust_hq) AS isKeyCustHq, MAX(w.is_sme) AS isSme,
       SUM(CASE WHEN w.stat_month = ? THEN w.dep_bal ELSE 0 END) AS depBal,
       SUM(CASE WHEN w.stat_month = ? THEN w.loan_bal ELSE 0 END) AS loanBal,
       SUM(CASE WHEN w.stat_month = ? THEN w.dep_avg_day ELSE 0 END) AS depAvgDay,
       SUM(CASE WHEN w.stat_month = ? THEN w.loan_avg_day ELSE 0 END) AS loanAvgDay,
       SUM(w.sett_debit_amt + w.sett_credit_amt) AS settAmtYear,
       SUM(w.sett_cnt_year) AS settCntYear,
""" + f"       SUM({_FEE_SUM}) AS feeYear,\n"
            + "       SUM(w.profit_dep + w.profit_loan + w.profit_fee) AS profitTotalYear\n"
            + joins + where_sql + " GROUP BY w.cust_id" + having_sql
            + " ORDER BY depBal DESC LIMIT ? OFFSET ?")
        rows = self._store.query(
            select_sql,
            [period, period, period, period] + where_params + having_params
            + [page_size, page_number * page_size])
        for r in rows:
            for k, v in list(r.items()):
                if isinstance(v, float):
                    r[k] = round(v, 2)
        return {"rows": rows, "total": total,
                "page": {"number": page_number, "size": page_size},
                "period": period, "orgId": org_id}

    # ---------------- 内部 ----------------

    def _screen(self, screen: str) -> ScreenSpec:
        spec = SCREENS.get(screen)
        if spec is None:
            raise UsageError(f"screen 非法: {screen}（允许 {list(SCREENS)}）")
        return spec

    def _validate_dim(self, spec: ScreenSpec, dim: str) -> None:
        if spec.row_axis == "DIM" and spec.dims and dim not in spec.dims:
            raise UsageError(
                f"dim 非法: {dim}（屏 {spec.screen_id} 允许 {list(spec.dims)}）")

    def _metric_keys(self, spec: ScreenSpec, biz_type: str | None) -> list[str]:
        if spec.screen_id == "segment-business":
            return list(_BIZ_METRICS[biz_type or "DEPOSIT"])
        return list(spec.metrics)

    def _totals(self, frame: dict, metric_keys: list[str]) -> dict:
        totals: dict[str, float] = {}
        for key in metric_keys:
            totals[key] = sum((m.get(key) or 0) for m in frame.values())
        return totals

    def _alerts(self, metric_keys: list[str], rows: list[dict]) -> list[dict]:
        threshold = float(self._params["alert_threshold"])
        alerts = []
        for row in rows:
            for key in metric_keys:
                mom = row.get(key + "Mom")
                if mom is not None and abs(mom) > threshold:
                    alerts.append({"dimValue": row["dimValue"], "metric": key,
                                   "direction": "up" if mom > 0 else "down",
                                   "mom": mom,
                                   "threshold": threshold})
        return alerts

    def _org_path(self, org_id: str) -> str:
        row = self._store.one(
            "SELECT org_path FROM dim_org WHERE org_id = ?", [org_id])
        if row is None:
            raise UsageError(f"orgId 未知: {org_id}")
        return row["org_path"]

    def _agg_sql(self) -> str:
        items = list(_AGG.items())
        if str(self._params.get("profit_source", "DERIVED")).upper() == "FTP":
            # FTP 口径：额外聚合真实 FTP 利润列（缺失时 _ftp_columns 抛 UsageError）
            items.extend((c, f"SUM(w.{c})") for c in self._ftp_columns())
        return ", ".join(f"{expr} AS {key}" for key, expr in items)

    def _aggregate(self, row_axis: str, org_id: str, period: str,
                   dim_values: list[str] | None) -> dict[str, dict]:
        """按行轴聚合单期：返回 {成员: {指标: 值}}（含派生指标）。"""
        dim_expr = self._dim_expr(row_axis)
        where = ["w.stat_month = ?",
                 "w.org_id IN (SELECT org_id FROM dim_org WHERE org_path LIKE ?)"]
        params: list = [period, self._org_path(org_id) + "%"]
        if dim_values and row_axis != "ORG":
            marks = ",".join("?" * len(dim_values))
            where.append(f"({dim_expr}) IN ({marks})")
            params.extend([str(v) for v in dim_values])
        sql = (f"SELECT ({dim_expr}) AS dim_value, {self._agg_sql()} "
               "FROM cbdm_cust_biz_wide w "
               "LEFT JOIN dim_industry di ON w.industry_code = di.industry_code "
               + ("JOIN dim_org o ON w.org_id = o.org_id "
                  if row_axis == "ORG" else "")
               + "WHERE " + " AND ".join(where) + " GROUP BY 1")
        frame: dict[str, dict] = {}
        for r in self._store.query(sql, params):
            member = r.pop("dim_value")
            r.update(self._derive(r))
            frame[member] = r
        return frame

    def _series_agg(self, dim: str, org_id: str, periods: list[str],
                    dim_value: str) -> dict[str, dict]:
        dim_expr = self._dim_expr(dim)
        # QA FAIL-2026-09-22-AN0-QA-01：ORG 行轴经 o.org_name 取值，本 SQL 原先缺
        # JOIN dim_org（与 _aggregate 不对称）⇒ BinderException 500。两处 JOIN 现保持一致。
        sql = (f"SELECT w.stat_month AS stat_month, {self._agg_sql()} "
               "FROM cbdm_cust_biz_wide w "
               "LEFT JOIN dim_industry di ON w.industry_code = di.industry_code "
               + ("JOIN dim_org o ON w.org_id = o.org_id " if dim == "ORG" else "")
               + "WHERE w.stat_month BETWEEN ? AND ? "
               "AND w.org_id IN (SELECT org_id FROM dim_org WHERE org_path LIKE ?) "
               f"AND ({dim_expr}) = ? GROUP BY 1")
        rows = self._store.query(sql, [periods[0], periods[-1],
                                       self._org_path(org_id) + "%", dim_value])
        frame: dict[str, dict] = {}
        for r in rows:
            p = r.pop("stat_month")
            r.update(self._derive(r))
            frame[p] = r
        return frame
