# API 文档 IR v1

`ApiDocument` 是语言适配器与渲染器之间唯一的数据契约。

```text
adapter(source, options) -> ApiDocument -> Markdown / Postman / cURL
```

字段：

- `ir_version`：当前为 `1`。
- `language`：源语言，例如 `java`。
- `framework`：API 框架，例如 `spring`。
- `endpoints`：方法、路径、参数绑定、请求体、响应类型和源码位置。
- `schemas`：以 `<language>:<qualified-name>` 为 key 的 DTO schema；同名 schema 不得合并。
- `Schema.enum_options`：可选的枚举成员列表，每项保存成员名、序列化取值、说明、附加属性及“取值是否已解析”。Java 适配器还记录枚举被整型/字符串字段通过注解引用时的取值；字段以 `enum_schema_id` 引用枚举 schema。渲染器依据字段类型选择实际 API 取值，供请求示例、字段说明和独立枚举表共用。
- `Endpoint.enum_bindings`：从当前接口方法的枚举调用推得的字段关联，按接口及参数分别应用到对应 DTO 字段，避免同一 DTO 在其他接口或其他参数串用枚举。
- `Field.access`：Java/Jackson 字段的读写方向。请求与响应在渲染前分别投影 schema，保证同一 DTO 的只读字段仅出现在响应、只写字段仅出现在请求。
- `Schema.ignored_properties`、`allow_getters`、`allow_setters`：保存类级 Jackson 忽略规则；展开继承字段时按请求或响应方向过滤，避免子类重新暴露被忽略的父类属性。
- `Endpoint.interface_notes`、`response_codes`：方法说明和响应码，分别渲染到标题下方和“更多信息”。
- `Field.wire_name`、`minimum`：保留 Java 属性名与实际请求键的区别，并让示例值遵守声明的数值下限。

新语言实现时，先提供适配器输出同一 IR，再复用现有渲染器。不要让渲染器读取源码、语言 AST、构建工具或框架注解。类型无法唯一解析时应保留未解析状态并告警，不能猜测同名类型。

类型引用在 IR 内部以 `TypeRef(name, schema_id, arguments)` 保存：字段的源码字符串只用于展示，渲染器按结构化类型引用展开 schema。泛型绑定以“schema ID + 完整实参”作为递归上下文，因此同一 `Box<T>` 在同一接口中同时出现 `Box<A>` 与 `Box<B>` 不会串型；`Child extends Base<Payload>` 和 `Map<String, Payload>` 也会保留实际的值类型。Java/Spring 适配器会为同包、显式 import 与唯一类型填充 schema ID；Python/FastAPI 适配器使用 Python 标准库 AST，并识别路由、`response_model`、`include_router`、模块导入和源代码中的 `Depends` 参数。需要更完整的跨包或泛型语义时，只在适配器或 IR 展开层增加按需解析，不让渲染器读取源码。
