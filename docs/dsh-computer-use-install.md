# DSH Computer Use 安装记录（Playwright MCP 桥接）

> 状态：已安装并端到端验证（2026-08-21）
> 位置：DSH web profile 插件层（非 DKWS 工程代码，属于 DSH 底座能力）

## 背景与结论

DSH 自身**没有内置** computer-use（无截图/点击/键盘原生工具），但随 DSH 交付了完整的
**MCP 客户端桥接插件** `@deepseek-ai/dsh-mcp-client`：每个插件实例连接一个外部 MCP
服务器，并把该服务器的工具注册进模型工具注册表，命名为 `mcp__<serverName>__<tool>`。

因此"安装 DSH computer use"= 让 DSH 的 MCP 桥接加载一个 computer-use MCP 服务器。
本次选用官方 **Playwright MCP**（`@playwright/mcp`，微软出品），提供浏览器自动化
computer use（导航/点击/输入/截图/快照/网络/表单等 24 个工具）。

## 安装内容

| 项目 | 值 |
|---|---|
| MCP 服务器 | `@playwright/mcp@0.0.79`（`playwright-mcp` CLI） |
| 桥接插件 | `@deepseek-ai/dsh-mcp-client`（DSH 内置，本部署已可解析） |
| 浏览器 | 系统 Google Chrome 150（`--browser chrome`，headless） |
| 工具命名空间 | `mcp__computer__*` |
| 生效方式 | profile 补丁层 HMR 热加载，**无需重启 DSH** |

### 安装步骤（已执行）

1. `pnpm --dir /home/szf/.dsh/profiles/web add @playwright/mcp`
   （写入 profile 依赖，`cli.js` 位于
   `/home/szf/.dsh/profiles/web/node_modules/@playwright/mcp/cli.js`）
2. 在 `/home/szf/.dsh/profiles/web/cordis.patch.yml` 插入 `mcp-computer` 插件行（见下）。
3. HMR 检测到补丁变更后事务性重放 patch，新行即刻挂载，`playwright-mcp` 子进程被拉起。
4. 工具注册到模型工具注册表（`Tool.listTools` 可见 `mcp__computer__*`）。

> 注：`playwright install chromium`（匹配 build 1237）下载停滞且非必需——
> 系统 Chrome 通道可用，故改用 `--browser chrome`，零下载。

## 配置（cordis.patch.yml）

```yaml
# DSH computer use: bridge the Playwright MCP server (browser automation)
# into the model tool registry as mcp__computer__<tool>.
- insert:
    - id: mcp-computer
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: stdio
        serverName: computer
        command: node
        args:
          - /home/szf/.dsh/profiles/web/node_modules/@playwright/mcp/cli.js
          - --headless
          - --browser
          - chrome
        cwd: /home/szf/.dsh/profiles/web
        toolCallTimeoutMs: 120000
        failOnStartupError: true
        reconnect:
          enabled: true
          initialDelayMs: 1000
          maxDelayMs: 30000
          maxAttempts: 10
```

要点：
- `serverName: computer` → 工具名 `mcp__computer__browser_navigate` 等。
- 子进程 env 采用 `scrubbedParentEnv()`（剔除凭据形态与过期 `DSH_*` 变量），
  `HOME` 保留，浏览器缓存路径正常解析。
- `--headless --browser chrome`：无头驱动系统 Chrome，与用户桌面 Chrome 实例隔离
  （playwright 使用独立临时 user-data-dir）。
- `failOnStartupError: true` 便于安装期诊断；稳定后可改 `false` 提高容错。

## 工具清单（24 个）

`browser_navigate` / `browser_navigate_back` / `browser_click` / `browser_type` /
`browser_press_key` / `browser_hover` / `browser_drag` / `browser_drop` /
`browser_snapshot` / `browser_find` / `browser_take_screenshot` / `browser_fill_form` /
`browser_select_option` / `browser_tabs` / `browser_resize` / `browser_wait_for` /
`browser_evaluate` / `browser_network_requests` / `browser_network_request` /
`browser_console_messages` / `browser_handle_dialog` / `browser_file_upload` /
`browser_run_code_unsafe` / `browser_close`

## 端到端验证（已通过）

1. `browser_navigate(http://127.0.0.1:3080)` → Page Title: DeepSeek Harness ✅
2. `browser_take_screenshot` → PNG 产出 ✅
3. `browser_navigate(http://127.0.0.1:8106/api/skill/health)` → 快照显示 10 个 Skill、
   status ok ✅（DKWS skill 服务）
4. `browser_navigate(http://127.0.0.1:8106/docs)` → Swagger UI，截图 1280x720 PNG ✅
   （产物：`/home/szf/.dsh/profiles/web/dsh-computer-use-verify.png`）

> 截图/快照文件默认写于 MCP server 的 `cwd`（profile 目录）下的 `.playwright-mcp/`。

## 运维

- **禁用**：从 `cordis.patch.yml` 删除 `mcp-computer` 行（HMR 热卸载，工具即刻消失）。
- **换用捆绑 chromium**：若希望版本与 playwright 绑定（不依赖系统 Chrome），
  运行 `pnpm --dir /home/szf/.dsh/profiles/web exec playwright install chromium`
  并去掉 args 中的 `--browser chrome`。
- **扩展桌面 X11 控制**：本机 `:0` 存在 X 会话且 `ffmpeg x11grab` 截图可用；
  若需真实桌面截图+鼠标键盘，可再插入一个 desktop-control MCP 服务器行
  （需 `apt install xdotool`），与 `mcp-computer` 并行，互不影响。
- **重启后持久性**：本配置属于 profile 补丁层，DSH 进程重启后自动重新加载。
