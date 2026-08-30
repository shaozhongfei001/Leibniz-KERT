package com.dkws.skillruntime.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * 技能执行结果，对齐内部契约 {@code docs/contracts/internal/schemas/execution-result.schema.json}。
 *
 * <p>契约必填字段：{@code requestId}、{@code runtimeRequestId}、{@code status}、
 * {@code usable}、{@code releaseAllowed}、{@code result}、{@code startedAt}、{@code completedAt}。
 *
 * <p>其中 {@code result} 为开放载荷对象（契约允许自由字段），
 * 而信封本身封闭（{@code additionalProperties: false}），
 * 因此业务字段必须放入 {@code result}，不得提升到顶层。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ExecutionResult(
        String requestId,
        String runtimeRequestId,
        String status,
        Boolean usable,
        Boolean releaseAllowed,
        Boolean degraded,
        String degradationReason,
        Map<String, Object> result,
        List<Map<String, Object>> errors,
        String startedAt,
        String completedAt,
        List<ToolCallReceipt> toolCallReceipts,
        List<ModelCallReceipt> modelCallReceipts,
        List<Map<String, Object>> trace
) {

    /** 执行状态：与契约 {@code status} 枚举逐一对应。 */
    public static final String STATUS_SUCCESS = "SUCCESS";
    public static final String STATUS_PARTIAL = "PARTIAL";
    public static final String STATUS_DEGRADED = "DEGRADED";
    public static final String STATUS_FAILED = "FAILED";

    /**
     * 构造成功结果。
     *
     * @param result 业务载荷，放入契约 {@code result} 开放对象
     * @return 可用且允许放行的成功结果
     */
    public static ExecutionResult success(
            String requestId,
            String runtimeRequestId,
            Map<String, Object> result,
            String startedAt,
            String completedAt,
            List<ToolCallReceipt> toolCallReceipts,
            List<ModelCallReceipt> modelCallReceipts
    ) {
        return new ExecutionResult(
                requestId, runtimeRequestId, STATUS_SUCCESS,
                Boolean.TRUE, Boolean.TRUE, Boolean.FALSE, null,
                result, List.of(),
                startedAt, completedAt,
                toolCallReceipts == null ? List.of() : toolCallReceipts,
                modelCallReceipts == null ? List.of() : modelCallReceipts,
                null
        );
    }

    /**
     * 构造降级结果。
     *
     * <p>降级结果按治理要求不允许放行（{@code releaseAllowed=false}）。
     *
     * @param degradationReason 降级原因，例如 {@code SANDBOX_UNAVAILABLE}
     * @return 标记降级且禁止放行的结果
     */
    public static ExecutionResult degraded(
            String requestId,
            String runtimeRequestId,
            Map<String, Object> result,
            String startedAt,
            String completedAt,
            String degradationReason,
            List<Map<String, Object>> errors
    ) {
        return new ExecutionResult(
                requestId, runtimeRequestId, STATUS_DEGRADED,
                Boolean.TRUE, Boolean.FALSE, Boolean.TRUE, degradationReason,
                result, errors == null ? List.of() : errors,
                startedAt, completedAt,
                List.of(), List.of(), null
        );
    }
}
