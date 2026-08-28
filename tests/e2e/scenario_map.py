"""5 大业务场景 API 调用链路映射

数据来源:
- GITS 后端 Controller: apps/api/.../api/controller/*.java
- GITS 前端 API: frontend/src/api/*.ts
- KERT skill 注册: src/dkws/application/skills.py
- GITS→KERT 适配器: DshHttpSkillExecutionAdapter.java (POST /api/skill/execute)

GITS→KERT 调用机制:
  DshHttpSkillExecutionAdapter.execute(SkillCommand) →
    POST {kert_base_url}/api/skill/execute
    Body: {"skillId": "...", "customerId": "...", "parameters": {...}}
    Response: {"skillId": "...", "status": "SUCCESS", "content": {...}}
"""

from __future__ import annotations

SCENARIOS: dict[str, dict] = {
    # =========================================================================
    # 场景1: 客户经理持续经营 (Engagement / Journey)
    # =========================================================================
    "continuous_operation": {
        "name": "客户经理持续经营",
        "description": "客户经理启动旅程→洞察分析→产品匹配→访前准备→访后跟进 完整闭环",
        "gits_api_calls": [
            # --- EngagementJourneyController ---
            {
                "method": "POST",
                "path": "/api/v1/engagement/journey/start",
                "body_template": {"customerId": "CUST-CORP-0001"},
                "description": "启动客户持续经营旅程，返回 journeyId + kycGapSummary",
                "controller": "EngagementJourneyController",
            },
            {
                "method": "GET",
                "path": "/api/v1/engagement/customer/{customerId}/operating-view",
                "body_template": None,
                "description": "获取客户经营总览（客户画像+经营数据+风险等级）",
                "controller": "EngagementJourneyController",
            },
            {
                "method": "GET",
                "path": "/api/v1/engagement/journey/{journeyId}",
                "body_template": None,
                "description": "查询旅程详情及当前阶段",
                "controller": "EngagementJourneyController",
            },
            {
                "method": "POST",
                "path": "/api/v1/engagement/journey/{journeyId}/postvisit",
                "body_template": {"notes": "访后记录内容"},
                "description": "记录访后跟进信息，推进旅程阶段",
                "controller": "EngagementJourneyController",
            },
            {
                "method": "POST",
                "path": "/api/v1/engagement/journey/{journeyId}/new-evidence",
                "body_template": {"evidenceType": "FINANCIAL", "content": "新证据内容"},
                "description": "提交新证据触发洞察更新",
                "controller": "EngagementJourneyController",
            },
            # --- V14DkwsIntegrationController (GITS→KERT 跨服务) ---
            {
                "method": "GET",
                "path": "/api/v14/gates/state/{customerId}",
                "body_template": None,
                "description": "查询 Gate 状态（GITS→KERT 跨服务调用）",
                "controller": "V14DkwsIntegrationController",
            },
            {
                "method": "POST",
                "path": "/api/v14/proposals",
                "body_template": {
                    "requestId": "REQ-001",
                    "customerId": "CUST-CORP-0001",
                    "context": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "生成服务建议书（GITS→KERT SP-20 跨服务调用）",
                "controller": "V14DkwsIntegrationController",
            },
            {
                "method": "POST",
                "path": "/api/v14/memories/extract",
                "body_template": {
                    "interactionId": "INT-001",
                    "customerId": "CUST-CORP-0001",
                },
                "description": "交互记忆抽取（GITS→KERT SP-21 跨服务调用）",
                "controller": "V14DkwsIntegrationController",
            },
            # --- CustomerJourneyController ---
            {
                "method": "GET",
                "path": "/api/v1/customer-journey/{customerId}",
                "body_template": None,
                "description": "获取客户旅程时间线",
                "controller": "CustomerJourneyController",
            },
            # --- CustomerContextController ---
            {
                "method": "GET",
                "path": "/api/v1/customer-context/{customerId}",
                "body_template": None,
                "description": "获取客户上下文信息",
                "controller": "CustomerContextController",
            },
            # --- OpportunityController ---
            {
                "method": "GET",
                "path": "/api/v1/opportunities",
                "body_template": None,
                "description": "查询机会列表",
                "controller": "OpportunityController",
            },
            {
                "method": "GET",
                "path": "/api/v1/opportunities/{opportunityId}",
                "body_template": None,
                "description": "查询机会详情",
                "controller": "OpportunityController",
            },
            # --- CommitmentController ---
            {
                "method": "GET",
                "path": "/api/v1/commitments",
                "body_template": None,
                "description": "查询承诺列表",
                "controller": "CommitmentController",
            },
            # --- CrmWritebackController ---
            {
                "method": "POST",
                "path": "/api/v1/crm-writeback",
                "body_template": {"action": "SYNC", "entityType": "CUSTOMER", "entityId": "CUST-CORP-0001"},
                "description": "CRM 回写（将 GITS 数据同步回 CRM）",
                "controller": "CrmWritebackController",
            },
        ],
        "kert_skill_ids": [
            "SP-20",           # 服务建议书生成
            "SP-21",           # 访前报告/交互记忆抽取
            "gates",           # Gate 状态查询
            "supply-chain",    # 供应链图谱
            "R1",              # 客户准入
        ],
        "kert_api_calls": [
            {
                "method": "POST",
                "path": "/api/skill/execute",
                "body_template": {
                    "skillId": "SP-20",
                    "customerId": "CUST-CORP-0001",
                    "parameters": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "KERT skill 执行统一入口",
            },
            {
                "method": "GET",
                "path": "/api/skill/gates/{customerId}",
                "body_template": None,
                "description": "KERT Gate 状态查询",
            },
            {
                "method": "GET",
                "path": "/api/skill/health",
                "body_template": None,
                "description": "KERT 健康检查",
            },
        ],
        "frontend_pages": [
            "views/engagement/OperatingView.vue",    # 客户经营总览页
            "views/engagement/JourneyTimeline.vue",   # 旅程时间线页
            "views/engagement/PrevisitPlan.vue",      # 访前计划页
        ],
        "expected_flow": (
            "1. 客户经理选择客户 → POST /api/v1/engagement/journey/start 启动旅程\n"
            "2. 系统返回 journeyId + kycGapSummary（含 KYC 差距摘要）\n"
            "3. GET /api/v1/engagement/customer/{id}/operating-view 获取经营总览\n"
            "4. GET /api/v14/gates/state/{id} 查询 Gate 状态（GITS→KERT）\n"
            "5. POST /api/v14/memories/extract 抽取交互记忆（GITS→KERT SP-21）\n"
            "6. POST /api/v14/proposals 生成服务建议书（GITS→KERT SP-20）\n"
            "7. POST /api/v1/engagement/journey/{id}/postvisit 记录访后跟进\n"
            "8. POST /api/v1/crm-writeback 回写 CRM"
        ),
    },

    # =========================================================================
    # 场景2: 访前报告生成 (Pre-visit Report / SP-21)
    # =========================================================================
    "previsit_report": {
        "name": "访前报告生成",
        "description": "交互记忆抽取→访前报告生成 完整链路",
        "gits_api_calls": [
            # --- V14DkwsIntegrationController ---
            {
                "method": "POST",
                "path": "/api/v14/memories/extract",
                "body_template": {
                    "interactionId": "INT-001",
                    "customerId": "CUST-CORP-0001",
                },
                "description": "交互记忆抽取（GITS→KERT SP-21 跨服务调用）",
                "controller": "V14DkwsIntegrationController",
            },
            {
                "method": "POST",
                "path": "/api/v14/proposals",
                "body_template": {
                    "requestId": "REQ-PREVISIT-001",
                    "customerId": "CUST-CORP-0001",
                    "context": {
                        "customerName": "华东精工",
                        "industry": "制造业",
                        "visitPurpose": "季度回顾",
                    },
                },
                "description": "生成访前报告/建议书（GITS→KERT SP-20 跨服务调用）",
                "controller": "V14DkwsIntegrationController",
            },
            {
                "method": "GET",
                "path": "/api/v14/gates/state/{customerId}",
                "body_template": None,
                "description": "查询 Gate 状态（访前需确认 Gate 完成度）",
                "controller": "V14DkwsIntegrationController",
            },
            # --- EngagementJourneyController ---
            {
                "method": "GET",
                "path": "/api/v1/engagement/customer/{customerId}/operating-view",
                "body_template": None,
                "description": "获取客户经营总览（访前背景信息）",
                "controller": "EngagementJourneyController",
            },
            {
                "method": "GET",
                "path": "/api/v1/engagement/journey/{journeyId}",
                "body_template": None,
                "description": "查询旅程详情（访前确认当前阶段）",
                "controller": "EngagementJourneyController",
            },
            # --- CustomerContextController ---
            {
                "method": "GET",
                "path": "/api/v1/customer-context/{customerId}",
                "body_template": None,
                "description": "获取客户上下文（访前补充信息）",
                "controller": "CustomerContextController",
            },
            # --- CustomerJourneyController ---
            {
                "method": "GET",
                "path": "/api/v1/customer-journey/{customerId}",
                "body_template": None,
                "description": "获取客户旅程时间线（历史交互记录）",
                "controller": "CustomerJourneyController",
            },
        ],
        "kert_skill_ids": [
            "SP-21",           # 交互记忆抽取 → 访前报告
            "SP-20",           # 服务建议书（访前报告核心输出）
            "gates",           # Gate 状态查询
        ],
        "kert_api_calls": [
            {
                "method": "POST",
                "path": "/api/skill/execute",
                "body_template": {
                    "skillId": "SP-21",
                    "customerId": "CUST-CORP-0001",
                    "parameters": {
                        "customerName": "华东精工",
                        "industry": "制造业",
                        "visitPurpose": "季度回顾",
                    },
                },
                "description": "KERT SP-21 skill 执行（访前报告生成）",
            },
            {
                "method": "GET",
                "path": "/api/skill/gates/{customerId}",
                "body_template": None,
                "description": "KERT Gate 状态查询",
            },
        ],
        "frontend_pages": [
            "views/engagement/PrevisitPlan.vue",      # 访前计划页
            "views/engagement/OperatingView.vue",     # 客户经营总览页
        ],
        "expected_flow": (
            "1. 客户经理选择客户 → GET /api/v1/engagement/customer/{id}/operating-view\n"
            "2. GET /api/v1/customer-journey/{id} 获取历史交互记录\n"
            "3. POST /api/v14/memories/extract 抽取交互记忆（GITS→KERT SP-21）\n"
            "4. GET /api/v14/gates/state/{id} 查询 Gate 完成度\n"
            "5. POST /api/v14/proposals 生成访前报告/建议书（GITS→KERT SP-20）\n"
            "6. 前端展示访前报告（含事实标签、产品推荐、实施计划）"
        ),
    },

    # =========================================================================
    # 场景3: 客户服务建议书 (Service Proposal / SP-20)
    # =========================================================================
    "service_proposal": {
        "name": "客户服务建议书",
        "description": "服务建议书生成 完整链路（含事实标签、产品推荐、实施计划）",
        "gits_api_calls": [
            # --- V14DkwsIntegrationController ---
            {
                "method": "POST",
                "path": "/api/v14/proposals",
                "body_template": {
                    "requestId": "REQ-SP20-001",
                    "customerId": "CUST-CORP-0001",
                    "context": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "生成服务建议书（GITS→KERT SP-20 跨服务调用），返回 proposalDraft + factLabels",
                "controller": "V14DkwsIntegrationController",
            },
            {
                "method": "GET",
                "path": "/api/v14/gates/state/{customerId}",
                "body_template": None,
                "description": "查询 Gate 状态（建议书需基于 Gate 完成度）",
                "controller": "V14DkwsIntegrationController",
            },
            # --- EngagementJourneyController ---
            {
                "method": "GET",
                "path": "/api/v1/engagement/customer/{customerId}/operating-view",
                "body_template": None,
                "description": "获取客户经营总览（建议书输入数据）",
                "controller": "EngagementJourneyController",
            },
            # --- KycInsightController ---
            {
                "method": "GET",
                "path": "/api/v1/kyc/insights/{customerId}",
                "body_template": None,
                "description": "获取 KYC 洞察（建议书风险分析输入）",
                "controller": "KycInsightController",
            },
            {
                "method": "GET",
                "path": "/api/v1/kyc/insights/{customerId}/claims",
                "body_template": None,
                "description": "获取 KYC 声明列表（建议书事实来源）",
                "controller": "KycInsightController",
            },
            # --- ClaimController ---
            {
                "method": "GET",
                "path": "/api/v1/claims",
                "body_template": None,
                "description": "查询声明列表（建议书事实标签来源）",
                "controller": "ClaimController",
            },
            # --- EvaluationController ---
            {
                "method": "GET",
                "path": "/api/v1/evaluations/{customerId}",
                "body_template": None,
                "description": "获取客户评估结果（建议书评分输入）",
                "controller": "EvaluationController",
            },
            # --- OpportunityController ---
            {
                "method": "GET",
                "path": "/api/v1/opportunities",
                "body_template": None,
                "description": "查询机会列表（建议书产品推荐来源）",
                "controller": "OpportunityController",
            },
            # --- CrmWritebackController ---
            {
                "method": "POST",
                "path": "/api/v1/crm-writeback",
                "body_template": {"action": "PROPOSAL", "entityType": "PROPOSAL", "entityId": "PROP-001"},
                "description": "建议书回写 CRM",
                "controller": "CrmWritebackController",
            },
        ],
        "kert_skill_ids": [
            "SP-20",           # 服务建议书生成（核心 skill）
            "gates",           # Gate 状态查询
            "R1",              # 客户准入
        ],
        "kert_api_calls": [
            {
                "method": "POST",
                "path": "/api/skill/execute",
                "body_template": {
                    "skillId": "SP-20",
                    "customerId": "CUST-CORP-0001",
                    "parameters": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "KERT SP-20 skill 执行（服务建议书生成）",
            },
        ],
        "frontend_pages": [
            "views/engagement/ServiceProposal.vue",   # 服务建议书页
            "views/engagement/OperatingView.vue",     # 客户经营总览页
        ],
        "expected_flow": (
            "1. GET /api/v1/engagement/customer/{id}/operating-view 获取客户画像\n"
            "2. GET /api/v1/kyc/insights/{id} 获取 KYC 洞察\n"
            "3. GET /api/v14/gates/state/{id} 查询 Gate 完成度\n"
            "4. POST /api/v14/proposals 生成服务建议书（GITS→KERT SP-20）\n"
            "5. 返回 proposalDraft（含事实标签 F/C/H/P/B/A）+ 产品推荐 + 实施计划\n"
            "6. POST /api/v1/crm-writeback 回写 CRM"
        ),
    },

    # =========================================================================
    # 场景4: 知识图谱/供应链图谱 (Knowledge Graph / Supply Chain)
    # =========================================================================
    "knowledge_graph": {
        "name": "知识图谱/供应链图谱",
        "description": "供应链图谱构建→节点/边数据→图谱可视化数据 完整链路",
        "gits_api_calls": [
            # --- SupplyChainGraphController ---
            {
                "method": "POST",
                "path": "/api/v1/engagement/supply-chain-graph",
                "body_template": {"customerId": "CUST-CORP-0001"},
                "description": "构建供应链图谱（GITS→KERT supply-chain 跨服务调用），返回 nodes + edges",
                "controller": "SupplyChainGraphController",
            },
            # --- KnowledgeMapController ---
            {
                "method": "GET",
                "path": "/api/v1/knowledge-maps",
                "body_template": None,
                "description": "查询知识地图列表",
                "controller": "KnowledgeMapController",
            },
            {
                "method": "GET",
                "path": "/api/v1/knowledge-maps/{mapId}",
                "body_template": None,
                "description": "查询知识地图详情",
                "controller": "KnowledgeMapController",
            },
            {
                "method": "GET",
                "path": "/api/v1/knowledge-maps/{mapId}/elements",
                "body_template": None,
                "description": "查询知识地图元素",
                "controller": "KnowledgeMapController",
            },
            # --- EngagementJourneyController ---
            {
                "method": "GET",
                "path": "/api/v1/engagement/customer/{customerId}/operating-view",
                "body_template": None,
                "description": "获取客户经营总览（图谱上下文）",
                "controller": "EngagementJourneyController",
            },
            # --- V14DkwsIntegrationController ---
            {
                "method": "GET",
                "path": "/api/v14/gates/state/{customerId}",
                "body_template": None,
                "description": "查询 Gate 状态（图谱关联 Gate）",
                "controller": "V14DkwsIntegrationController",
            },
        ],
        "kert_skill_ids": [
            "supply-chain",    # 供应链图谱构建
            "R1",              # 客户准入（图谱准入校验）
            "gates",           # Gate 状态查询
        ],
        "kert_api_calls": [
            {
                "method": "POST",
                "path": "/api/skill/execute",
                "body_template": {
                    "skillId": "supply-chain",
                    "customerId": "CUST-CORP-0001",
                    "parameters": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "KERT supply-chain skill 执行（供应链图谱构建）",
            },
            {
                "method": "POST",
                "path": "/api/skill/execute",
                "body_template": {
                    "skillId": "R1",
                    "customerId": "CUST-CORP-0001",
                    "parameters": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "KERT R1 skill 执行（客户准入）",
            },
        ],
        "frontend_pages": [
            "views/engagement/SupplyChainGraph.vue",  # 供应链图谱可视化页
            "views/knowledge/KnowledgeMap.vue",       # 知识地图页
        ],
        "expected_flow": (
            "1. GET /api/v1/engagement/customer/{id}/operating-view 获取客户画像\n"
            "2. POST /api/v1/engagement/supply-chain-graph 构建供应链图谱（GITS→KERT supply-chain）\n"
            "3. 返回 nodes（企业/客户/供应商节点）+ edges（供应链关系）\n"
            "4. GET /api/v1/knowledge-maps 查询知识地图\n"
            "5. GET /api/v14/gates/state/{id} 关联 Gate 状态\n"
            "6. 前端渲染图谱可视化"
        ),
    },

    # =========================================================================
    # 场景5: 客户洞察 (Customer Insight / KYC)
    # =========================================================================
    "customer_insight": {
        "name": "客户洞察",
        "description": "客户洞察→KYC 差距分析→风险信号→产品匹配 完整链路",
        "gits_api_calls": [
            # --- KycInsightController ---
            {
                "method": "GET",
                "path": "/api/v1/kyc/insights/{customerId}",
                "body_template": None,
                "description": "获取 KYC 洞察摘要（风险信号+差距分析+产品匹配）",
                "controller": "KycInsightController",
            },
            {
                "method": "GET",
                "path": "/api/v1/kyc/insights/{customerId}/claims",
                "body_template": None,
                "description": "获取 KYC 声明列表（事实声明+推断声明）",
                "controller": "KycInsightController",
            },
            {
                "method": "POST",
                "path": "/api/v1/kyc/insights/{customerId}/claims",
                "body_template": {"claimType": "FACT", "content": "声明内容", "source": "CRM"},
                "description": "记录 KYC 声明（触发洞察更新）",
                "controller": "KycInsightController",
            },
            # --- ClaimController ---
            {
                "method": "GET",
                "path": "/api/v1/claims",
                "body_template": None,
                "description": "查询声明列表",
                "controller": "ClaimController",
            },
            {
                "method": "POST",
                "path": "/api/v1/claims",
                "body_template": {"claimType": "FACT", "content": "声明内容", "customerId": "CUST-CORP-0001"},
                "description": "创建声明",
                "controller": "ClaimController",
            },
            # --- EngagementJourneyController ---
            {
                "method": "POST",
                "path": "/api/v1/engagement/journey/start",
                "body_template": {"customerId": "CUST-CORP-0001"},
                "description": "启动旅程（返回 kycGapSummary）",
                "controller": "EngagementJourneyController",
            },
            {
                "method": "GET",
                "path": "/api/v1/engagement/customer/{customerId}/operating-view",
                "body_template": None,
                "description": "获取客户经营总览（含风险等级 riskLevel）",
                "controller": "EngagementJourneyController",
            },
            # --- V14DkwsIntegrationController ---
            {
                "method": "GET",
                "path": "/api/v14/gates/state/{customerId}",
                "body_template": None,
                "description": "查询 Gate 状态（洞察关联 Gate）",
                "controller": "V14DkwsIntegrationController",
            },
            # --- EvaluationController ---
            {
                "method": "GET",
                "path": "/api/v1/evaluations/{customerId}",
                "body_template": None,
                "description": "获取客户评估结果",
                "controller": "EvaluationController",
            },
            # --- CustomerContextController ---
            {
                "method": "GET",
                "path": "/api/v1/customer-context/{customerId}",
                "body_template": None,
                "description": "获取客户上下文（洞察补充信息）",
                "controller": "CustomerContextController",
            },
            # --- OpportunityController ---
            {
                "method": "GET",
                "path": "/api/v1/opportunities",
                "body_template": None,
                "description": "查询机会列表（产品匹配结果）",
                "controller": "OpportunityController",
            },
        ],
        "kert_skill_ids": [
            "gates",           # Gate 状态查询（KYC 差距分析）
            "SP-20",           # 服务建议书（产品匹配）
            "SP-21",           # 交互记忆抽取
            "R1",              # 客户准入
        ],
        "kert_api_calls": [
            {
                "method": "GET",
                "path": "/api/skill/gates/{customerId}",
                "body_template": None,
                "description": "KERT Gate 状态查询（KYC 差距分析）",
            },
            {
                "method": "POST",
                "path": "/api/skill/execute",
                "body_template": {
                    "skillId": "SP-20",
                    "customerId": "CUST-CORP-0001",
                    "parameters": {"customerName": "华东精工", "industry": "制造业"},
                },
                "description": "KERT SP-20 skill 执行（产品匹配）",
            },
        ],
        "frontend_pages": [
            "views/engagement/OperatingView.vue",     # 客户经营总览页（含风险等级）
            "views/engagement/KycInsight.vue",        # KYC 洞察页
            "views/engagement/ClaimList.vue",          # 声明列表页
        ],
        "expected_flow": (
            "1. POST /api/v1/engagement/journey/start 启动旅程（返回 kycGapSummary）\n"
            "2. GET /api/v1/engagement/customer/{id}/operating-view 获取客户画像（含 riskLevel）\n"
            "3. GET /api/v1/kyc/insights/{id} 获取 KYC 洞察（风险信号+差距分析）\n"
            "4. GET /api/v1/kyc/insights/{id}/claims 获取声明列表\n"
            "5. GET /api/v14/gates/state/{id} 查询 Gate 状态（GITS→KERT）\n"
            "6. GET /api/v1/evaluations/{id} 获取评估结果\n"
            "7. GET /api/v1/opportunities 查询产品匹配结果\n"
            "8. POST /api/v14/proposals 生成建议书（含产品推荐）"
        ),
    },
}


# ---------------------------------------------------------------------------
# 辅助: GITS→KERT 跨服务调用机制
# ---------------------------------------------------------------------------
GITS_TO_KERT_BRIDGE = {
    "adapter_class": "DshHttpSkillExecutionAdapter",
    "adapter_path": "apps/api/src/main/java/com/gien/gits/adapter/skill/DshHttpSkillExecutionAdapter.java",
    "port_interface": "SkillExecutionPort",
    "port_path": "modules/scenario-hermes/src/main/java/com/gien/gits/engagement/port/SkillExecutionPort.java",
    "call_mechanism": (
        "GITS Service 注入 SkillExecutionPort → "
        "DshHttpSkillExecutionAdapter.execute(SkillCommand) → "
        "POST {kert_base_url}/api/skill/execute → "
        "KERT SkillRegistry 查找 skill → "
        "执行 skill handler → 返回 SkillResult"
    ),
    "request_format": {
        "skillId": "string  # skill 标识，如 SP-20/SP-21/gates/supply-chain/R1",
        "customerId": "string  # 客户 ID",
        "parameters": "dict  # skill 参数，如 customerName/industry/visitPurpose",
    },
    "response_format": {
        "skillId": "string  # skill 标识",
        "status": "string  # SUCCESS / PARTIAL / ERROR",
        "content": "dict  # skill 执行结果",
    },
}


# ---------------------------------------------------------------------------
# 辅助: KERT skill 注册表
# ---------------------------------------------------------------------------
KERT_SKILL_REGISTRY = {
    "SP-20": {
        "name": "服务建议书生成",
        "handler": "service_proposal.handler",
        "module": "src/dkws/application/service_proposal.py",
        "description": "生成客户服务建议书，含事实标签(F/C/H/P/B/A)、产品推荐、实施计划",
    },
    "SP-21": {
        "name": "访前报告/交互记忆抽取",
        "handler": "previsit_report.handler",
        "module": "src/dkws/application/previsit_report.py",
        "description": "抽取交互记忆，生成访前报告",
    },
    "gates": {
        "name": "Gate 状态查询",
        "handler": "gates.handler",
        "module": "src/dkws/application/gates.py",
        "description": "查询客户 Gate 状态，含 KYC 差距分析",
    },
    "supply-chain": {
        "name": "供应链图谱构建",
        "handler": "supply_chain.handler",
        "module": "src/dkws/application/supply_chain.py",
        "description": "构建供应链图谱，返回节点(nodes)和边(edges)",
    },
    "R1": {
        "name": "客户准入",
        "handler": "customer_admission.handler",
        "module": "src/dkws/application/customer_admission.py",
        "description": "客户准入评估",
    },
}


# ---------------------------------------------------------------------------
# 辅助: 按场景获取 API 调用列表
# ---------------------------------------------------------------------------
def get_scenario_api_calls(scenario_key: str, *, include_kert: bool = True) -> list[dict]:
    """获取指定场景的完整 API 调用列表。

    Args:
        scenario_key: 场景键名，如 "continuous_operation"
        include_kert: 是否包含 KERT 直连 API 调用

    Returns:
        API 调用列表，每个元素包含 method/path/body_template/description
    """
    scenario = SCENARIOS.get(scenario_key)
    if not scenario:
        raise ValueError(f"未知场景: {scenario_key}")

    calls = list(scenario["gits_api_calls"])
    if include_kert:
        calls.extend(scenario.get("kert_api_calls", []))
    return calls


def get_all_gits_paths() -> set[str]:
    """获取所有 GITS API 路径集合（去重）。"""
    paths: set[str] = set()
    for scenario in SCENARIOS.values():
        for call in scenario["gits_api_calls"]:
            # 将路径参数占位符统一为 {param} 格式
            path = call["path"]
            paths.add(path)
    return paths


def get_all_kert_skill_ids() -> set[str]:
    """获取所有 KERT skill ID 集合（去重）。"""
    ids: set[str] = set()
    for scenario in SCENARIOS.values():
        ids.update(scenario.get("kert_skill_ids", []))
    return ids
