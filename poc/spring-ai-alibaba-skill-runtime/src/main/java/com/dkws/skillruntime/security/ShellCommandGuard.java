package com.dkws.skillruntime.security;

import java.util.List;
import java.util.Set;

/**
 * PoC 最小 Shell 命令白名单。
 */
public class ShellCommandGuard {

    private final Set<String> allowedCommands;

    public ShellCommandGuard(List<String> allowedCommands) {
        this.allowedCommands = Set.copyOf(allowedCommands);
    }

    public void validate(String commandLine) {
        if (commandLine == null || commandLine.isBlank()) {
            throw new IllegalArgumentException("empty shell command");
        }
        String command = commandLine.trim().split("\\s+")[0];
        if (!allowedCommands.contains(command)) {
            throw new SecurityException("shell command not allowed: " + command);
        }
    }
}
