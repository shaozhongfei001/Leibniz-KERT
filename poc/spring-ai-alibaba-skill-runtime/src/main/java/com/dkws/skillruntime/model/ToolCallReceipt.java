package com.dkws.skillruntime.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 工具调用回执，对齐内部契约 {@code docs/contracts/internal/schemas/tool-call-receipt.schema.json}。
 *
 * <p>契约必填字段：{@code toolId}、{@code toolVersion}、{@code skillId}、
 * {@code skillVersion}、{@code startedAt}、{@code completedAt}、{@code status}。
 * 其余为可选证据字段，为 {@code null} 时不参与序列化，
 * 以满足契约 {@code additionalProperties: false} 下的最小回执形态。
 *
 * <p>{@code startedAt} / {@code completedAt} 使用 RFC3339 UTC 字符串
 * （形如 {@code 2026-08-30T10:15:21Z}），与契约 {@code format: date-time} 一致。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ToolCallReceipt(
        String toolId,
        String toolVersion,
        String skillId,
        String skillVersion,
        String inputHash,
        String policyDecisionId,
        String sandboxProfileHash,
        String startedAt,
        String completedAt,
        Integer exitCode,
        Double cpuTime,
        Double memoryPeak,
        String outputHash,
        Boolean outputTruncated,
        Boolean networkUsed,
        SideEffectReceipt sideEffectReceipt,
        String status,
        String errorCode
) {

    /** 工具调用状态：与契约 {@code status} 枚举逐一对应。 */
    public static final String STATUS_OK = "ok";
    public static final String STATUS_FAILED = "failed";
    public static final String STATUS_BLOCKED = "blocked";
    public static final String STATUS_TIMEOUT = "timeout";
    public static final String STATUS_ERROR = "error";

    /**
     * 副作用回执，对应契约中 {@code sideEffectReceipt} 开放对象。
     *
     * @param kind   副作用类型，例如 {@code NONE}
     * @param detail 补充说明
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record SideEffectReceipt(String kind, String detail) {
    }

    /**
     * 构造成功回执。
     *
     * @return 状态为 {@code ok} 的回执
     */
    public static ToolCallReceipt ok(
            String toolId,
            String toolVersion,
            String skillId,
            String skillVersion,
            String startedAt,
            String completedAt
    ) {
        return new ToolCallReceipt(
                toolId, toolVersion, skillId, skillVersion,
                null, null, null,
                startedAt, completedAt,
                0, null, null, null, null, Boolean.FALSE, null,
                STATUS_OK, null
        );
    }

    /**
     * 构造被策略拦截的回执。
     *
     * @param errorCode 拦截原因错误码，例如 {@code TOOL_NOT_ALLOWED}
     * @return 状态为 {@code blocked} 的回执
     */
    public static ToolCallReceipt blocked(
            String toolId,
            String toolVersion,
            String skillId,
            String skillVersion,
            String startedAt,
            String completedAt,
            String errorCode
    ) {
        return new ToolCallReceipt(
                toolId, toolVersion, skillId, skillVersion,
                null, null, null,
                startedAt, completedAt,
                null, null, null, null, null, Boolean.FALSE, null,
                STATUS_BLOCKED, errorCode
        );
    }
}
