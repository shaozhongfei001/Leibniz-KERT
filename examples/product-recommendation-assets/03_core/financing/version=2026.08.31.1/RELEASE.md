# 发布记录（financing / version=2026.08.31.1）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

- `release_id`: REL-2026.08.31.1
- `domain`: financing
- `release_version`: 2026.08.31.1
- `previous_version`: null
- `status`: CANDIDATE（非 CLI 正式 PUBLISHED）

## 资产清单（asset_manifest）

> `sha256` 为「SHA-256(完整文件字节)」；`content_hash` 为产品卡自身「SHA-256(去除 content_hash 行后的文件字节)」。

| path | schema | asset_id | version | content_hash | sha256 |
|---|---|---|---|---|---|
| product-cards/PROD-FIN-001.md | product_card/v1 | PROD-FIN-001 | 1.0.0-candidate | sha256:e9738c56547c94dd7c797dc57e14c63082bc1f07f241a3780ef3c9bbcf6fecca | 64d98edecd7708c1b01d3fdd0ca0188055a21556b9d1e942b96f60f29e6d94bb |
| product-cards/PROD-FIN-002.md | product_card/v1 | PROD-FIN-002 | 1.0.0-candidate | sha256:27a46c30f430764d2d0bea1c62541b35009189e4226270ca89501523092865f0 | be991644bd6df7dfe8e1acc21247a1c4cc1a9f678c2ff5859ccd040ef182f518 |
| product-cards/PROD-FIN-003.md | product_card/v1 | PROD-FIN-003 | 1.0.0-candidate | sha256:f24d57c847ad25bb5f45512de0455c3df12354292232ed766293165ccd451942 | 196f57a66ffba586f510f7eb6844003117c90a39a1bd4ba09a3952929d50bd73 |

## 说明（如实）

本发布记录为**候选示例**，未经 `Publisher.publish` 流程生成：无 G3 门禁结果、无审核决定（`90_control/decisions`）、无 `.dkws_workspace` 标记。**待 dkws CLI 链路正式落库（Gate 0 限定项）**后由 CLI 重算清单哈希并原子提交。
