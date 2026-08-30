package com.dkws.skillruntime.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 模型调用回执，对齐内部契约 {@code docs/contracts/internal/schemas/model-call-receipt.schema.json}。
 *
 * <p>契约必填字段：{@code model}、{@code promptHash}、{@code inputTokens}、
 * {@code outputTokens}、{@code latencyMs}、{@code status}。
 *
 * <p>{@code latencyMs} 与 {@code estimatedCost} 在契约中为 {@code number}，
 * 因此使用 {@code Double} 而非整型，避免精度语义与契约不一致。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ModelCallReceipt(
        String model,
        String promptHash,
        String paramsHash,
        Integer inputTokens,
        Integer outputTokens,
        Double estimatedCost,
        Double latencyMs,
        Boolean degraded,
        String degradationReason,
        String status
) {

    /** 模型调用状态：与契约 {@code status} 枚举逐一对应。 */
    public static final String STATUS_OK = "ok";
    public static final String STATUS_ERROR = "error";
    public static final String STATUS_DEGRADED = "degraded";

    /**
     * 构造成功回执。
     *
     * @param promptHash 提示词摘要，契约必填，用于可审计复现
     * @return 状态为 {@code ok} 的回执
     */
    public static ModelCallReceipt ok(
            String model,
            String promptHash,
            int inputTokens,
            int outputTokens,
            double latencyMs
    ) {
        return new ModelCallReceipt(
                model, promptHash, null,
                inputTokens, outputTokens, null, latencyMs,
                Boolean.FALSE, null, STATUS_OK
        );
    }

    /**
     * 构造降级回执。
     *
     * @param degradationReason 降级原因，例如 {@code MODEL_TIMEOUT}
     * @return 状态为 {@code degraded} 的回执
     */
    public static ModelCallReceipt degraded(
            String model,
            String promptHash,
            int inputTokens,
            int outputTokens,
            double latencyMs,
            String degradationReason
    ) {
        return new ModelCallReceipt(
                model, promptHash, null,
                inputTokens, outputTokens, null, latencyMs,
                Boolean.TRUE, degradationReason, STATUS_DEGRADED
        );
    }
}
