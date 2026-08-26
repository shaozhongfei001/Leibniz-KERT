# ADR-013：服务认证与安全边界（候选）

> 状态：CANDIDATE_AWAITING_OWNER
> 日期：2026-08-26

## 背景

当前无鉴权、无 TLS、无限流、无请求大小限制，构成生产上线 Blocker。

## 决策

首个生产候选采用：

- API Key 作为服务到服务认证
- 密钥只保存哈希或通过 Secret Provider 注入
- TLS 由可信反向代理/网关终止，DKWS 默认不监听公网
- 生产 profile 若对外监听且 `auth_enabled=false` 则 fail-fast 拒绝启动
- 限流、请求体上限、超时、CORS/Host 校验为必备控制
- Gate/管理端点禁止匿名调用

## 影响

- GITS 配置改为 `DKWS_API_KEY`
- 契约 v2 增加 401/403/429/413
- 需要密钥轮换、吊销、过期、作用域

## 关闭条件

- 安全测试覆盖 401/403/429/413
- Secret 轮换测试通过
- Owner 批准
