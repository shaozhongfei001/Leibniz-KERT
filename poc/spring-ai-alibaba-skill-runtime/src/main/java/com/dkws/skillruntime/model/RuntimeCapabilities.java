package com.dkws.skillruntime.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

/**
 * 运行时能力声明，对齐内部契约
 * {@code docs/contracts/internal/schemas/runtime-capabilities.schema.json}。
 *
 * <p>契约必填字段仅 {@code runtimeVersion}、{@code contractVersion}、{@code status}，
 * 其余为可选。{@code contractHash} 是双端契约一致性锚点：
 * 其值必须等于 {@code scripts/internal_contract_hash.py} 重算出的 bundle 哈希。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RuntimeCapabilities(
        String runtimeVersion,
        String contractVersion,
        String contractHash,
        String frameworkVersion,
        List<String> activatedSkills,
        String sandboxCapability,
        Boolean degraded,
        String status
) {

    /** 运行时状态：与契约 {@code status} 枚举逐一对应。 */
    public static final String STATUS_OK = "ok";
    public static final String STATUS_DEGRADED = "degraded";

    /** 沙箱能力：与契约 {@code sandboxCapability} 枚举逐一对应。 */
    public static final String SANDBOX_AVAILABLE = "available";
    public static final String SANDBOX_UNAVAILABLE = "unavailable";
    public static final String SANDBOX_DISABLED = "disabled";
}
