# DKWS 静态侧栏菜单改造计划（审阅稿）

> 目标：在 DSH 左侧栏提供**固定的、刷新后依然存在**的「DKWS 平台」菜单入口与面板页，
> 取代当前"刷新后丢失"的动态插件入口。本计划不改动 DKWS 业务代码（`dkws/`），
> 只新增一个 DSH 静态 client 插件包并重建 web 产物。

## 1. 现状与机制结论（已调研确认）

| 项 | 结论 |
|---|---|
| 动态插件为何刷新丢失 | Client UI 运行在浏览器页面内存，刷新清空注册；定义在进程内（Host）持久 |
| 静态 UI 如何实现 | `packages/client/ui-*` 静态插件包：`package.json` 带 `dsh.client` 声明 + `exports["./client"]`，`src/client/index.ts` 注册 Slots，构建进 apps/web bundle，**刷新持久** |
| 侧栏可扩展点 | `sidebar.footer.action`（list，可加条目，replaceRisk none）；`settings.section`（list，可加完整页面）；`sidebar.workspaces` 为 ui-workspace 独占（single），加"菜单项"需改其本体 |
| 执行 dkws CLI | shell/subprocess 未直接暴露为 Remote；需在插件的 host 半区注册一个 `@Remote` 服务（如 `ctx.dkws.run`），client 经 ctx 调用（参照 message-feedback 的 Remote 模式） |

## 2. 目标形态

- **左侧栏底部（设置旁）**：静态「DKWS 平台」按钮（窄条模式显示「DK」小方块）；
- **完整面板页**：注册为 `settings.section` 的「DKWS 平台」页（设置菜单中可见），或点击按钮弹出的 overlay（静态化当前浮层）；
- 点击任一路径打开面板：工作区概览 / 检索 / 数据查询 / 规则评估 / 图谱 / 溯源 / CLI；
- **刷新后所有入口与功能均持久存在**。

## 3. 技术方案

### 3.1 新增包 `packages/client/ui-dkws`

```
packages/client/ui-dkws/
├── package.json          # name=@deepseek-ai/dsh-client-ui-dkws
│                         # dsh.client: { inject: [...], platform: "web" }
│                         # exports: { "./client": .../client.js, ".": .../index.js }
├── tsdown.client.ts      # client bundle 构建配置（参照 ui-commands）
├── src/
│   ├── index.ts          # host 半区：注册 Remote 服务 ctx.dkws（执行 dkws CLI）
│   ├── client/
│   │   ├── index.ts      # client 半区：apply(ctx) 注册
│   │   │                 #   sidebar.footer.action（静态按钮）
│   │   │                 #   settings.section（DKWS 平台页）或 shell.overlay（浮层）
│   │   ├── DkwsPanel.tsx # 面板组件（移植当前动态插件 UI）
│   │   └── locales.ts    # 中文文案（参照 ui-sidebar 模式）
```

### 3.2 Host 半区：Remote 服务（执行 dkws CLI）

- 在 `src/index.ts` 用 `@Remote` 注册服务方法：
  - `dkws.inspect()` → `dkws inspect --output json`
  - `dkws.search/queryData/evaluateRule/graph/trace/run(...)` → 对应 CLI（同当前动态插件 Host 逻辑）
- 执行方式：Host 半区 `ctx.shell`（bash）运行 `/…/dkws/.venv/bin/dkws <args>`，`PYTHONPATH=…/dkws/src`，cwd=`demo_workspace`；
- 安全：仅允许白名单子命令，输出经 JSON 解析返回；日志脱敏。

### 3.3 构建与部署

1. `packages/client/ui-dkws` 纳入 monorepo（workspace 依赖声明）；
2. 重建 apps/web bundle：`pnpm --filter @deepseek-ai/web build`（vite build）；
3. **重启运行中的 DSH web 服务**，使 Host 重新扫描 `dsh.client` 并加载新 bundle（当前 3080 服务的 clientModules 表需刷新）；
4. 验证：刷新 `http://127.0.0.1:3080` → 侧栏「DKWS 平台」按钮存在且功能可用；再次刷新依然存在。

## 4. 实施步骤（约 6-10 步，估计 2-4 小时）

| # | 步骤 | 输出/验证 |
|---|---|---|
| 1 | 脚手架：创建 `ui-dkws` 包（package.json/tsdown/exports，参照 ui-commands） | 包可被 pnpm 解析 |
| 2 | host 半区：Remote 服务 `ctx.dkws`（bash 执行 dkws CLI，白名单） | `@Remote` 方法签名正确 |
| 3 | client 半区：静态注册 `sidebar.footer.action` 按钮 + 面板页/浮层 | 本地类型检查通过 |
| 4 | 面板组件移植（当前动态插件 UI 改为 TSX） | 构建无错 |
| 5 | `pnpm build` 重建 web bundle | dist 更新 |
| 6 | 重启 3080 web 服务 | 新 bundle 生效 |
| 7 | 验证：侧栏按钮、面板功能、刷新持久性 | 全部通过 |
| 8 | 收尾：停用动态插件入口（可选保留）、更新文档 | 干净状态 |

## 5. 风险与回滚

| 风险 | 等级 | 对策 |
|---|---|---|
| 修改 DSH 部署本体，构建/重启可能影响当前运行环境 | 中 | 构建前记录当前 3080 状态；失败可回滚 dist |
| Remote 服务（@Remote + typert）学习成本 | 中 | 参照 message-feedback/plugin-inventory 既有模式 |
| bundle 构建时间与格式问题（tsdown client 配置） | 中 | 先参照 ui-commands 完整配置逐项复制 |
| 重启 web 服务导致当前会话短暂中断 | 低 | 提前告知；重启后验证 URL |
| **回滚**：删除 `ui-dkws` 包 + 重建 + 重启即可完全恢复；不动其他包 | — | 全程只新增一个包，不改既有文件 |

## 6. 备选（若您不愿改 DSH 本体）

- 保持当前动态插件（输入框按钮 + 侧栏补充），刷新后说一声即恢复（零风险，当前可用）；
- 或把入口改成设置页 `settings.section`（仍是动态插件，刷新仍丢）。

## 7. 需要您确认的点

1. **是否授权修改 DSH checkout**（新增包 + 重建 + 重启 3080）？
2. 面板形态偏好：**A.** 设置菜单里的「DKWS 平台」页；**B.** 点击侧栏按钮弹出浮层（推荐，贴近现状）；**C.** 两者都要；
3. 侧栏按钮文字：展开「DKWS 平台」/ 窄条「DK」（可调）；
4. 完成后是否**停用**当前动态插件 `dkws-1`（避免双入口）。
