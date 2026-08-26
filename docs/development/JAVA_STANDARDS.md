# Java 开发规范

## 版本

- Java 21
- Spring Boot 3.3.x
- Spring AI Alibaba 1.1.2.x
- Maven 构建

## 代码风格

- 遵循 Java 官方命名规范
- 使用 record 表示不可变 DTO
- 使用 `@ConfigurationProperties` 或 `@Value` 读取配置
- 不打印敏感信息

## 项目结构

```text
poc/spring-ai-alibaba-skill-runtime/
├── src/main/java/com/dkws/skillruntime/
│   ├── config/
│   ├── controller/
│   ├── service/
│   ├── model/
│   └── security/
└── src/test/java/
```

## 测试

- 单元测试：JUnit 5
- 集成测试：Spring Boot Test
- 契约测试：内部 API Schema 校验

## 禁止

- Java Runtime 不直接写 SQLite
- Java Runtime 不直接访问 DKWS 五层工作区
- 不向 GITS 暴露 Java Runtime API
- 生产禁用 autoReload
