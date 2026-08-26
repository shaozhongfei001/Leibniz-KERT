package com.dkws.skillruntime.controller;

import com.dkws.skillruntime.model.RuntimeCapabilities;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/v1/runtime")
public class InternalRuntimeController {

    @GetMapping("/health")
    public RuntimeCapabilities health() {
        return new RuntimeCapabilities(
                "0.0.1-poc2",
                "1.0.0-candidate",
                "64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550",
                "spring-ai-alibaba-1.1.2.0",
                java.util.List.of("demo-skill", "data-skill"),
                "disabled",
                false,
                "ok"
        );
    }
}
