---
activationContract: AC-SERVICE-PROPOSAL-002
name: 基于交互记忆的建议书更新
routeMode: MAP_FIRST
assetDependencies: [ASSET-KNOW-PROPOSAL-TEMPLATE, ASSET-DATA-INTERACTION-MEMORY]
gateSequence: [G0, G1, G2, G3, G4, G5]
---

# AC-SERVICE-PROPOSAL-002 激活合同

持续经营阶段更新建议书：先读交互记忆与既有建议书（MAP_FIRST），再装配模板。
触发：proposalType=UPDATE 且 engagementPhase ∈ {ACTIVE_ENGAGEMENT, PROPOSAL_DELIVERED}。
