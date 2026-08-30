package com.dkws.skillruntime.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.Map;

/**
 * 运行时错误，对齐内部契约 {@code docs/contracts/internal/schemas/runtime-error.schema.json}。
 *
 * <p>契约必填字段：{@code code}、{@code message}。{@code details} 为开放对象，
 * 用于承载定位信息（如幂等冲突的双方 {@code payloadHash}）。
 *
 * <p>本类型只表达内部 Runtime 错误，不得直接透传给外部调用方：
 * 对外错误响应由 Python Core 统一构造。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RuntimeError(
        String code,
        String message,
        Boolean retryable,
        Map<String, Object> details
) {

    /** 幂等键复用但载荷不同：不可重试。 */
    public static final String CODE_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT";
    /** 超过执行计划截止时间：可重试。 */
    public static final String CODE_DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED";
    /** 工具未在计划授权列表内：不可重试。 */
    public static final String CODE_TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED";
    /** 沙箱不可用：不可重试，结果不得放行。 */
    public static final String CODE_SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE";
    /** 执行计划不符合契约：不可重试。 */
    public static final String CODE_INVALID_PLAN = "INVALID_PLAN";

    /**
     * 构造幂等冲突错误。
     *
     * @param idempotencyKey     被复用的幂等键
     * @param expectedPayloadHash 首次记录的载荷摘要
     * @param actualPayloadHash   本次请求的载荷摘要
     * @return 不可重试的冲突错误
     */
    public static RuntimeError idempotencyConflict(
            String idempotencyKey,
            String expectedPayloadHash,
            String actualPayloadHash
    ) {
        return new RuntimeError(
                CODE_IDEMPOTENCY_CONFLICT,
                "Idempotency key reused with a different payloadHash",
                Boolean.FALSE,
                Map.of(
                        "idempotencyKey", idempotencyKey,
                        "expectedPayloadHash", expectedPayloadHash,
                        "actualPayloadHash", actualPayloadHash
                )
        );
    }

    /**
     * 构造不可重试错误。
     *
     * @param code    契约错误码
     * @param message 面向运维的错误说明
     * @return 不可重试错误
     */
    public static RuntimeError permanent(String code, String message) {
        return new RuntimeError(code, message, Boolean.FALSE, null);
    }

    /**
     * 构造可重试错误。
     *
     * @param code    契约错误码
     * @param message 面向运维的错误说明
     * @return 可重试错误
     */
    public static RuntimeError retryable(String code, String message) {
        return new RuntimeError(code, message, Boolean.TRUE, null);
    }
}
