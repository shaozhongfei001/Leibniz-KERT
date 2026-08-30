package com.dkws.skillruntime.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * 执行计划，对齐内部契约 {@code docs/contracts/internal/schemas/execution-plan.schema.json}。
 *
 * <p>由 Python Core 下发、Java Skill Runtime 消费。Runtime 不得自行发明字段：
 * 契约声明 {@code additionalProperties: false}，因此本 DTO 显式声明
 * {@code @JsonIgnoreProperties(ignoreUnknown = false)}，
 * 使未知字段在反序列化阶段即失败，而不是被静默丢弃。
 *
 * <p>控制面字段（{@code skillHash}、{@code activationPlanHash}、{@code policyId}、
 * {@code idempotencyKey}、{@code payloadHash}、{@code allowedToolIds}）全部必填，
 * 缺失即视为非法计划，Runtime 应拒绝执行。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = false)
public record ExecutionPlan(
        String contractVersion,
        String requestId,
        String traceparent,
        String tenantId,
        Map<String, Object> customerScope,
        String skillId,
        String skillVersion,
        String skillHash,
        String activationPlanHash,
        String policyId,
        String promptPolicyRef,
        String modelPolicyRef,
        String deadline,
        String idempotencyKey,
        String payloadHash,
        List<String> allowedToolIds,
        List<String> knowledgeSourceRefs,
        Map<String, Object> contextPackage
) {

    /**
     * 判断指定工具是否在计划授权范围内。
     *
     * <p>{@code allowedToolIds} 为空数组表示零工具授权，任何工具调用都应被拦截。
     *
     * @param toolId 待校验的工具标识
     * @return 在授权列表内返回 {@code true}
     */
    public boolean allowsTool(String toolId) {
        return allowedToolIds != null && allowedToolIds.contains(toolId);
    }
}
