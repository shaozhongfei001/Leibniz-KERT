package com.dkws.skillruntime.security;

import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * 安全解压：防止 Zip Slip、超量文件、超限大小。
 */
public class ZipSafeExtractor {

    private final long maxZipSizeBytes;
    private final int maxFileCount;

    public ZipSafeExtractor(long maxZipSizeBytes, int maxFileCount) {
        this.maxZipSizeBytes = maxZipSizeBytes;
        this.maxFileCount = maxFileCount;
    }

    public Path extractTo(MultipartFile file, Path targetRoot) throws IOException {
        if (file.getSize() > maxZipSizeBytes) {
            throw new IllegalArgumentException("zip too large: " + file.getSize());
        }

        Path temp = Files.createTempFile("skill-upload-", ".zip");
        try (InputStream in = file.getInputStream()) {
            Files.copy(in, temp, StandardCopyOption.REPLACE_EXISTING);
        }

        try (ZipFile zipFile = new ZipFile(temp.toFile())) {
            Enumeration<? extends ZipEntry> entries = zipFile.entries();
            int count = 0;
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                count++;
                if (count > maxFileCount) {
                    throw new IllegalArgumentException("too many files in zip: " + count);
                }
                Path resolved = targetRoot.resolve(entry.getName()).normalize();
                if (!resolved.startsWith(targetRoot.normalize())) {
                    throw new SecurityException("zip slip detected: " + entry.getName());
                }
                if (entry.isDirectory()) {
                    Files.createDirectories(resolved);
                    continue;
                }
                Files.createDirectories(resolved.getParent());
                try (InputStream is = zipFile.getInputStream(entry)) {
                    Files.copy(is, resolved, StandardCopyOption.REPLACE_EXISTING);
                }
            }
        } finally {
            Files.deleteIfExists(temp);
        }
        return targetRoot;
    }
}
