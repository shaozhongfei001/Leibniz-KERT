# 当前活动版本（financing）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

- `scope_type`: CORE_DOMAIN
- `scope_id`: financing
- `target_version`: 2026.08.31.1
- `target_release_id`: REL-2026.08.31.1
- `status`: CANDIDATE

## 切换说明

当前（候选）指向版本 `2026.08.31.1`。**待 dkws CLI 链路正式落库（Gate 0 限定项）**：正式发布后由 `Publisher._write_current` 原子切换指针，失败保留旧指针；本文件为人工预填示例，非 CLI 产物。

## 回滚说明

回滚仅切换指针，不删除任何版本目录；版本目录 `version=*` 发布后不可变，只可退役。
