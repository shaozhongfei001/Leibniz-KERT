# 开发提示词：供应链图谱分析报告展示（gits 侧对接）

> 用途：交给 gits Java 项目组（或 AI 编码助手）实现「服务调用后以可视化报告展示供应链图谱分析结果」。
> 契约版本：DKWS Skill 执行 API v1.2（`docs/dd/skill-execute-api-contract.md`）。
> 参考实现：DKWS 服务端 `dkws/src/dkws/application/report.py` 与
> 样本页面 `docs/dd/supply_chain_report_sample.html`（浏览器打开可看视觉效果）。

---

## 提示词正文（可直接复制）

```
你是一名资深 Java 后端/前端工程师，为「银行智能访前作战单」项目实现供应链图谱分析报告展示功能。

## 背景
DKWS（DeepSeek Harness 上的文件目录型知识服务模拟平台）已提供 Skill 执行服务：
- POST /api/skill/execute：执行技能，响应 JSON 中 data.result 为 SK-FRONT-002 供应链图谱分析结果（nodes 三段式节点 + edges 有向关系边 + interpretation 四类解读），data.reportUrl 指向可视化报告页 /api/skill/report/{requestId}。
- GET /api/skill/report/{requestId}：DKWS 已提供定制「供应链图谱分析报告」HTML（Neo4j 风格力导向图谱 + 解读卡片 + 明细表）。但本需求要求 gits 侧自研展示，不依赖 DKWS 报告页（DKWS 页面仅作视觉参考）。

## 输入数据结构（data.result）
- nodes: [{ id, name, layer: supplier|enterprise|customer, type, industry, annualAmount(元), share(0-1), trend: up|flat|down|unknown, dataSource: T-CORE-001|T-EXT-001|MERGED, verifyStatus: VERIFIED|PENDING }]
- edges: [{ source, target, relation: purchase|sale, direction: in|out, annualAmount, share, settlement(结算/账期) }]
- interpretation: { supplyChainPosition, bargainingPower, concentrationRisk(list), keyChanges, overallAssessment, followUpQuestions(list), confidence }
- buildStatus: complete | partial（输入不足时部分降级，UI 须如实展示，不得补全虚构）

## 实现要求
1. 报告页必须包含四块：①头部元信息（客户名/客户ID/生成时间/buildStatus 徽章）；②统计卡片（节点数/边数/上游供应商数/下游客户数/置信度）；③三段式供应链图谱可视化；④解读章节（供应链位置/议价能力/集中度风险/关键变动/综合研判/访前必问事项）+ 节点/边明细表。
2. 图谱可视化须为**力导向布局**（Neo4j Browser 风格，可参考 vis-network 9.x 或 Cytoscape.js）：
   - 节点按 layer 着色：supplier=蓝 #4d9fff，enterprise=红 #ef476f，customer=青 #2dd4a7，带发光/阴影；
   - 边为带箭头有向边，颜色灰蓝 #4a5d85，悬停/选中显示"关系+金额"标签（如"采购 1200 万"）；
   - 选中节点：高亮其 1 跳邻居，其余节点变暗（opacity≈0.12），并弹出详情面板（名称/ID/层级/金额/占比/趋势/核验状态/数据源）；
   - 名称标签：核心企业常显，其余节点在缩放比例≥0.55 或悬停/选中时显示；
   - 交互：滚轮缩放、拖拽平移、双击聚焦、复位视图按钮。
3. 暗色主题（背景 #0b1322），中文界面，字体 Noto Sans SC / 微软雅黑。
4. 金额格式化为"万/亿"（≥1e4 显示 X.X 万，≥1e8 显示 X.XX 亿）；占比显示百分比。
5. buildStatus=partial 时：解读章节正常渲染，图谱与表格按实际数据渲染，页面上标注"部分降级，仅供参考"。
6. reportUrl 仅用于跳转参考；gits 侧数据一律取自 execute 响应 JSON，不解析 DKWS 报告页 HTML。
7. 服务端只需实现 GET /api/skill/report/{requestId} 时返回自研 HTML 页面（可用 Thymeleaf/Velocity/字符串模板），404 处理：缓存过期（10 分钟）返回友好提示"报告已过期，请重新执行"。

## 验收标准
- 用真实 execute 响应（含 3+ 供应商、3+ 客户、完整 interpretation）渲染，图谱清晰可交互；
- 选中任一节点：邻居高亮、其余变暗、详情面板正确；
- 悬停边显示关系+金额；缩放后非核心节点名称可见；
- buildStatus=partial 用例如实展示且不报错；
- 金额/占比/趋势格式化正确；暗色主题无样式错乱；主流浏览器（Chrome/Edge）无控制台报错。
```

---

## 给实现方的补充说明

### 为什么 gits 侧自研而不是直接用 DKWS 报告页
- DKWS 报告页服务于演示与联调；生产上 gits 需要把图谱嵌入自己的作战单/控制台，
  自研渲染（同一份 JSON 数据）可保持视觉体系一致、离线可用、并支持二次加工。

### 关键渲染技术选型（参考）
- 数据量预期：单客户图谱通常 ≤ 几十节点；无需超大规模优化。
- 推荐 vis-network 9.x（单文件 ~670KB，CDN 或本地 vendor 均可）；若需更强样式定制选 Cytoscape.js + cose/fcose 布局。
- 力导向物理参数参考（vis-network）：barnesHut { gravitationalConstant:-4200, centralGravity:0.05, springLength:110, springConstant:0.04, damping:0.4 }，stabilization iterations≈260。

### 参考文件
- 契约：`docs/dd/skill-execute-api-contract.md`（v1.2，含 reportUrl 与 SK-FRONT-002 输出结构）
- DKWS 参考实现：`dkws/src/dkws/application/report.py`
- 视觉参考：`docs/dd/supply_chain_report_sample.html`（浏览器直接打开）
- 独立大图谱示例（1064 节点，Neo4j 风格，供样式参考）：`dkws/examples/output/supply_chain_graph_1064.html`

### 服务端接口（gits 需要实现的）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/skill/execute | 调用 DKWS，取 data.result + data.reportUrl |
| GET | /api/skill/report/{requestId} | gits 自研报告页（数据取自本地保存的 execute 结果，勿回源 DKWS） |
