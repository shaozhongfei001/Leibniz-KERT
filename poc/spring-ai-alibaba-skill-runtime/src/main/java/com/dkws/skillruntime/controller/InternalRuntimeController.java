package com.dkws.skillruntime.controller;

import com.dkws.skillruntime.model.RuntimeCapabilities;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 内部 Runtime 控制端点，对应内部契约
 * {@code docs/contracts/internal/openapi/dkws-skill-runtime-internal-v1.yaml}。
 *
 * <p>该端点仅供 Python Core 内部调用，不对外暴露；GITS 只能通过
 * Python Core 的公共 HTTP 接口间接触达。
 */
@RestController
@RequestMapping("/internal/v1/runtime")
public class InternalRuntimeController {

    /** 内部契约候选版本，与 OpenAPI {@code info.version} 一致。 */
    public static final String CONTRACT_VERSION = "1.0.0-candidate";

    /**
     * 内部契约 bundle 哈希。
     *
     * <p>取值必须等于 {@code python scripts/internal_contract_hash.py} 的
     * {@code bundle_hash}；由 Java 侧契约测试与 Python 侧证据共同守护，
     * 任一端漂移都会导致测试失败。
     */
    public static final String CONTRACT_HASH =
            "64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550";

    private static final String RUNTIME_VERSION = "0.0.1-poc2";
    private static final String FRAMEWORK_VERSION = "spring-ai-alibaba-1.1.2.0";

    /**
     * 返回运行时能力声明。
     *
     * @return 符合 {@code runtime-capabilities.schema.json} 的能力声明
     */
    @GetMapping("/health")
    public RuntimeCapabilities health() {
        return new RuntimeCapabilities(
                RUNTIME_VERSION,
                CONTRACT_VERSION,
                CONTRACT_HASH,
                FRAMEWORK_VERSION,
                List.of("demo-skill", "data-skill"),
                RuntimeCapabilities.SANDBOX_DISABLED,
                Boolean.FALSE,
                RuntimeCapabilities.STATUS_OK
        );
    }
}
