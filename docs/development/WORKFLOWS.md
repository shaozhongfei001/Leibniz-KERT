# 开发流程

## 分支模型

```text
main
 └── develop
      └── feature/<workstream-id>
```

## 标准流程

1. 同步 `develop`
2. 创建 `feature/<id>`
3. 开发 + 测试
4. 提交
5. 推送
6. 创建 PR 到 `develop`
7. 通过 CI 与人工评审后合并

## 发布流程

1. 从 `develop` 合并到 `main`
2. 打 tag
3. 生成发布 manifest
4. 更新证据与文档

## 禁止

- 未经授权直接 push `main`
- 未经授权 merge
- 在无测试证据时宣称完成
