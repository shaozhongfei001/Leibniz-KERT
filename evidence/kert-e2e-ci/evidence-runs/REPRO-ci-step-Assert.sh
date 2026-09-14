# 独立于 pytest 内部钩子的第二道下限断言（TECH_LEAD_DECISION D-8）：
# 口径为「errors=0 且 failed=0 且 passed>=下限 且 skipped<=上限」，
# 下限/上限由账本中按文件列出的分组**现场重算**，不信任账本自报的结论。
python - <<'PY'
import json
import os
import sys
path = os.path.join(os.environ["RUNNER_TEMP"], "e2e-coverage-ledger.json")
if not os.path.exists(path):
    print("::error::覆盖账本缺失（%s）——pytest 未正常完成，拒绝判定为通过" % path)
    sys.exit(1)
with open(path, encoding="utf-8") as fh:
    ledger = json.load(fh)
groups = ledger["groups"]
expected_min = len(groups["no_service"]) + len(groups["kert_only"])
expected_max = len(groups["gits_only"]) + len(groups["multi_end"])
print("E2E 覆盖账本：collected=%d passed=%d skipped=%d failed=%d errors=%d"
      % (ledger["collected"], ledger["passed"], ledger["skipped"],
         ledger["failed"], ledger["errors"]))
print("  下限 passed>=%d（无服务 %d + 仅 KERT %d）"
      % (expected_min, len(groups["no_service"]), len(groups["kert_only"])))
print("  上限 skipped<=%d（仅 GITS %d + 多端/含前端 %d）"
      % (expected_max, len(groups["gits_only"]), len(groups["multi_end"])))
print("  覆盖口径：%s" % ledger["coverage"])
for nodeid, reason in sorted(ledger["uncovered_reasons"].items()):
    print("  未覆盖（显式登记，非通过）：%s  [%s]" % (nodeid, reason))
problems = []
if ledger["errors"] != 0:
    problems.append("errors=%d（必须 0）" % ledger["errors"])
if ledger["failed"] != 0:
    problems.append("failed=%d（必须 0）" % ledger["failed"])
if ledger["passed"] < expected_min:
    problems.append("passed=%d < 下限 %d" % (ledger["passed"], expected_min))
if ledger["skipped"] > expected_max:
    problems.append("skipped=%d > 上限 %d" % (ledger["skipped"], expected_max))
if ledger["collected"] != (ledger["passed"] + ledger["skipped"]
                           + ledger["failed"] + ledger["errors"]):
    problems.append("计数不自洽：collected=%d，四态之和=%d"
                    % (ledger["collected"],
                       ledger["passed"] + ledger["skipped"]
                       + ledger["failed"] + ledger["errors"]))
if problems:
    for problem in problems:
        print("::error::E2E 覆盖账本下限断言失败：%s" % problem)
    sys.exit(1)
print("✓ 覆盖账本下限断言通过（errors=0, failed=0, passed>=%d, skipped<=%d）"
      % (expected_min, expected_max))
PY
