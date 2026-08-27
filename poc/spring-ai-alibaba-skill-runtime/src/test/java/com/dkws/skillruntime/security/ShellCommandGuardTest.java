package com.dkws.skillruntime.security;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * Shell 命令白名单测试。
 *
 * <p><b>重要局限（必须如实记录，不得当作安全结论）</b>：
 * 当前 {@link ShellCommandGuard} 只检查命令行首个 token，因此
 * 管道 / 重定向 / 复合命令（{@code echo x | sh}、{@code echo x; rm -rf /}）
 * 在首 token 合法时**不会被拦截**。这正是施工令要求「不接受自由 shell 字符串，
 * 应使用固定 executable + argv Schema」的原因。
 *
 * <p>本测试把该局限固化为机器事实：{@code documentsCompoundCommandBypass}
 * 断言「当前实现确实放过复合命令」，因此不得声称 ShellTool 已安全。
 * 生产 ShellTool 必须保持关闭，实际执行走
 * {@code sandbox/bwrap_runner.py} 的 executable+argv 结构化接口。
 */
class ShellCommandGuardTest {

    private final ShellCommandGuard guard = new ShellCommandGuard(List.of("ls", "cat", "echo"));

    @Test
    void allowsWhitelistedCommand() {
        assertDoesNotThrow(() -> guard.validate("ls -la"));
        assertDoesNotThrow(() -> guard.validate("echo hello"));
    }

    @Test
    void rejectsNonWhitelistedCommand() {
        assertThrows(SecurityException.class, () -> guard.validate("rm -rf /"));
        assertThrows(SecurityException.class, () -> guard.validate("curl http://evil"));
        assertThrows(SecurityException.class, () -> guard.validate("/bin/sh -c id"));
    }

    @Test
    void rejectsEmptyCommand() {
        assertThrows(IllegalArgumentException.class, () -> guard.validate(""));
        assertThrows(IllegalArgumentException.class, () -> guard.validate("   "));
        assertThrows(IllegalArgumentException.class, () -> guard.validate(null));
    }

    @Test
    void documentsCompoundCommandBypass() {
        // 已知局限：首 token 合法即通过，复合命令未被拦截。
        // 该行为是「free-form shell 不安全」的证据，不是通过项。
        assertDoesNotThrow(() -> guard.validate("echo x; rm -rf /tmp/x"));
        assertDoesNotThrow(() -> guard.validate("echo x | sh"));
        assertDoesNotThrow(() -> guard.validate("cat /etc/passwd > /tmp/leak"));
        assertDoesNotThrow(() -> guard.validate("echo $(id)"));
    }
}
