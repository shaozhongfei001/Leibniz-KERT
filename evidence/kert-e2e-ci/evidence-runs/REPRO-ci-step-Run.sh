# 注意：pyproject 的 addopts 已含 -q，此处再传 -q 会变成 -qq，
# 连「N passed, M skipped」汇总行都会被抑制 —— 只传 -rs 打印 skip reason。
python -m pytest tests/e2e/ -rs
