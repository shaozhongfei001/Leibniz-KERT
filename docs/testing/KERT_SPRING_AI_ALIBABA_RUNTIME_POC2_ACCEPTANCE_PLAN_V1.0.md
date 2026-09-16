# Spring AI Alibaba Runtime POC-2 验收计划 V1.0

> 日期：2026-08-26
> 状态：CANDIDATE

## 十二项准入标准

1. 至少两个不同 Skill 动态注册，工具集合不能硬编码
2. read_skill→groupedTools→真实 ToolCall→结构化 receipt 可重放
3. Skill 包版本/hash/签名校验、显式 activate、原子切换和回滚通过
4. Python Core→Java Runtime 鉴权、幂等、deadline、取消、Trace、错误合同通过
5. Java Runtime 不直接写 SQLite，不直接访问 Core 文件目录
6. 故障注入通过：重启、超时、模型失败、重复请求、网络中断
7. nsjail/bwrap 下 Python/Shell 受控执行通过，安全负向用例通过
8. 自动化单元、契约、集成、安全和恢复测试有原始报告
9. SBOM、依赖/许可证/漏洞报告生成
10. 单机资源和延迟基准符合 Owner 批准 NFR
11. Compose/systemd 独立安装，不依赖外部智能体平台
12. 独立 QA 在受控 commit 上复跑签署

## 当前状态

1-4、6-12 未全部关闭；POC-2 当前为 PARTIAL_PASS。
