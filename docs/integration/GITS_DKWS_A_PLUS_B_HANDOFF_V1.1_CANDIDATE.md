# GITS × DKWS A+B 交接 V1.1（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01

## 边界

- GITS 只通过 DKWS Python Core 公共 HTTP/OpenAPI 调用
- GITS 不直连 Java Skill Runtime
- GITS 不感知 DKWS 内部 Java Runtime 拓扑

## 顺序

1. B：移除 Mock/H2/fallback 伪成功，fail-closed 空态
2. A：恢复 GITS→DKWS 公共 HTTP Adapter
3. 对 Python Core 完成 R1、供应链、SP-20、SP-21、Gate 真实 E2E
4. Java Runtime 后续内部接入，GITS 契约不变

## 配置

```yaml
dkws:
  base-url: "${DKWS_BASE_URL:http://127.0.0.1:8106}"
  api-key: "${DKWS_API_KEY:}"
```

不新增 Java Runtime 地址配置。

## 验收

- GITS 不再本地拼装 DKWS-owned 能力
- 未配置/不可达/认证失败/契约错误时显示空态
- 真实 HTTP 调用 Python Core 成功
- 保留 requestId/traceId
- `UAT_PASS=NO` 保持，直到 Owner 签署
