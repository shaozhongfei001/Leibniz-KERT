# 通用开发 Rules

## 架构边界

- Python Core 是唯一公共入口
- Java Runtime 不对外、不写 SQLite、不直接访问五层工作区
- GITS 只走公共 HTTP

## 文档纪律

- 不静默覆盖历史文档
- 新增候选文件，登记 superseded
- 所有冲突进入 `docs/governance/DKWS_DOCUMENT_CONFLICT_REGISTER.md`

## 测试纪律

- 不得用 Mock 测试代替真实 E2E
- 不得把框架日志当作 ToolCall Receipt
- 所有测试必须记录命令、退出码、环境、原始输出

## 状态纪律

- 不自行宣布生产就绪
- 不自行宣布 GITS UAT 通过
- 不自行签署独立 QA
