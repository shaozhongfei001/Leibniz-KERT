# ADR-014：独立服务端产品边界（候选）

> 状态：CANDIDATE_AWAITING_OWNER
> 日期：2026-08-26

## 背景

DKWS 被定位为独立服务端软件，但现有文档/部署/凭据/Skill 资产仍与外部智能体运行平台耦合。

## 决策

- DKWS 产品运行不依赖任何 Agent Harness 或外部智能体运行平台
- 外部系统（GITS、智能体、前端）只能是 API 客户端
- 配置命名使用产品中性 `DKWS_*`
- 密钥从 DKWS 自身 Secret Provider 注入
- Skill 资产随 DKWS 发布包自带，支持版本/哈希/签名

## 影响

- 需要 `dkws-admin`、独立部署包、干净环境验收
- 现有 `serve_skill_service.py` 的凭据注入需改造
- 文档中的 DSH 耦合需标记为可选客户端/开发集成

## 关闭条件

- 干净主机/容器不安装外部智能体平台，可完成安装、启动、Skill 查询/执行、任务恢复
