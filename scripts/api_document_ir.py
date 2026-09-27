"""Language-neutral API documentation intermediate representation."""
from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TypeRef:
    """A resolved type, retaining generic arguments instead of flattening them to text."""
    name: str
    schema_id: str = ""
    arguments: Tuple["TypeRef", ...] = ()

    def display_name(self) -> str:
        return self.name + ("<" + ", ".join(argument.display_name() for argument in self.arguments) + ">"
                            if self.arguments else "")


@dataclass(frozen=True)
class EnumOption:
    member_name: str
    api_value: Any = None
    description: str = ""
    attributes: str = ""
    value_resolved: bool = False
    reference_value: Any = None
    reference_resolved: bool = False
    reference_attributes: str = ""
    properties: Dict[str, Any] = dataclass_field(default_factory=dict)
    description_property: str = ""


@dataclass
class Field:
    name: str
    type_name: str
    description: str = ""
    required: bool = False
    notes: str = ""
    example: Any = None
    location: str = ""
    schema_id: str = ""
    type_ref: Optional[TypeRef] = None
    enum_schema_id: str = ""
    minimum: Optional[int] = None
    enum_value_hint: str = ""
    wire_name: str = ""
    access: str = ""


@dataclass(frozen=True)
class ResponseCode:
    code: str
    message: str


@dataclass(frozen=True)
class EnumBinding:
    schema_id: str
    field_name: str
    enum_schema_id: str
    value_hint: str = ""
    parameter_name: str = ""


@dataclass
class Endpoint:
    name: str
    notes: str
    method: str
    path: str
    parameters: List[Field]
    request_body: Optional[Field]
    response_type: str
    source: str
    content_type: str = ""
    response_schema_id: str = ""
    interface_notes: str = ""
    response_codes: List[ResponseCode] = dataclass_field(default_factory=list)
    enum_bindings: List[EnumBinding] = dataclass_field(default_factory=list)


@dataclass
class Schema:
    id: str
    name: str
    qualified_name: str
    parent: str
    fields: List[Field]
    parent_schema_id: str = ""
    type_parameters: List[str] = dataclass_field(default_factory=list)
    enum_options: List[EnumOption] = dataclass_field(default_factory=list)
    ignored_properties: List[str] = dataclass_field(default_factory=list)
    allow_getters: bool = False
    allow_setters: bool = False


@dataclass
class ApiDocument:
    ir_version: int
    language: str
    framework: str
    endpoints: List[Endpoint]
    schemas: Dict[str, Schema]

    @classmethod
    def from_legacy(cls, language: str, framework: str, endpoints: List[Endpoint], classes: Dict[str, List[Field]]):
        return cls(1, language, framework, endpoints, {
            f"{language}:{name}": Schema(f"{language}:{name}", name, name, "", fields)
            for name, fields in classes.items()
        })

    def filtered(self, endpoint_names: set):
        return replace(self, endpoints=[endpoint for endpoint in self.endpoints if endpoint.name in endpoint_names])

    def for_direction(self, direction: str):
        excluded = "READ_ONLY" if direction == "request" else "WRITE_ONLY"
        return replace(self, schemas={schema_id: replace(schema, fields=[value for value in schema.fields
                       if value.access.split(".")[-1] != excluded],
                       ignored_properties=[] if (direction == "request" and schema.allow_setters)
                       or (direction == "response" and schema.allow_getters) else schema.ignored_properties)
                       for schema_id, schema in self.schemas.items()})

    def for_endpoint(self, endpoint: Endpoint):
        schemas = dict(self.schemas)
        parameters = list(endpoint.parameters)
        request_body = endpoint.request_body
        by_parameter = {}
        for binding in endpoint.enum_bindings:
            by_parameter.setdefault(binding.parameter_name, []).append(binding)
        for parameter_name, bindings in by_parameter.items():
            original = next((field for field in parameters if field.name == parameter_name), None)
            if original is None and request_body and request_body.name == parameter_name:
                original = request_body
            schema = self.schemas.get(original.schema_id) if original else None
            if not schema:
                continue
            clone_id = schema.id + "#" + endpoint.source + "#" + parameter_name
            fields = list(schema.fields)
            for binding in bindings:
                fields = [replace(field, enum_schema_id=binding.enum_schema_id, enum_value_hint=binding.value_hint)
                          if field.name == binding.field_name and not field.enum_schema_id else field
                          for field in fields]
            schemas[clone_id] = replace(schema, id=clone_id, fields=fields)
            parameters = [replace(field, schema_id=clone_id, type_ref=None)
                          if field.name == parameter_name else field for field in parameters]
            if request_body and request_body.name == parameter_name:
                request_body = replace(request_body, schema_id=clone_id, type_ref=None)
        specialized = replace(endpoint, parameters=parameters, request_body=request_body)
        return replace(self, endpoints=[specialized], schemas=schemas)

    def normalized(self):
        def normalize_field(value: Field) -> Field:
            return replace(value, type_ref=self.type_ref(value))

        schemas = {
            schema_id: replace(schema, fields=[normalize_field(value) for value in schema.fields])
            for schema_id, schema in self.schemas.items()
        }
        endpoints = [replace(endpoint,
                             parameters=[normalize_field(value) for value in endpoint.parameters],
                             request_body=normalize_field(endpoint.request_body) if endpoint.request_body else None)
                     for endpoint in self.endpoints]
        return replace(self, endpoints=endpoints, schemas=schemas)

    def type_ref(self, value: Field) -> TypeRef:
        return value.type_ref or self._parse_type(value.type_name, value.schema_id)

    def response_ref(self, endpoint: Endpoint) -> TypeRef:
        return self._parse_type(endpoint.response_type, endpoint.response_schema_id)

    def fields_for_type(self, value: TypeRef, seen=None) -> List[Field]:
        schema = self.schemas.get(value.schema_id) if value.schema_id else self._schema_for_type(value.name)
        if not schema:
            return []
        key = (schema.id, value.display_name())
        seen = seen or set()
        if key in seen:
            return []
        bindings = dict(zip(schema.type_parameters or (["T"] if value.arguments else []), value.arguments))
        parents: List[Field] = []
        if schema.parent:
            parent = self._substitute(self._parse_type(schema.parent, schema.parent_schema_id), bindings)
            parents = self.fields_for_type(parent, seen | {key})
        parents = [item for item in parents if item.name not in schema.ignored_properties
                   and (item.wire_name or item.name) not in schema.ignored_properties]
        return parents + [self._with_type(item, self._substitute(self.type_ref(item), bindings))
                          for item in schema.fields]

    def classes(self) -> Dict[str, List[Field]]:
        by_name: Dict[str, List[Schema]] = {}
        for schema in self.schemas.values():
            by_name.setdefault(schema.name, []).append(schema)
        return {
            name: self.fields_for_type(TypeRef(schema.qualified_name, schema.id))
            for name, values in by_name.items() if len(values) == 1
            for schema in values
        }

    def classes_for(self, values: List[Field]) -> Dict[str, List[Field]]:
        # Compatibility view for callers of the original script API. Rendering uses TypeRef directly.
        return self.classes()

    def _schema_for_type(self, type_name: str) -> Optional[Schema]:
        raw = _raw_type(type_name)
        base_schemas = [schema for schema in self.schemas.values() if "#" not in schema.id]
        direct = [schema for schema in base_schemas if schema.qualified_name == raw]
        if len(direct) == 1:
            return direct[0]
        if "." in raw:
            return None
        matches = [schema for schema in base_schemas if schema.name == raw.split(".")[-1]]
        return matches[0] if len(matches) == 1 else None

    def _parse_type(self, type_name: str, schema_id: str = "") -> TypeRef:
        union_parts = _split_arguments(_raw_type(type_name), "|")
        if len(union_parts) > 1:
            return TypeRef("Union", "", tuple(self._parse_type(part, schema_id) for part in union_parts))
        if _raw_type(type_name).endswith("[]"):
            return TypeRef("List", "", (self._parse_type(_raw_type(type_name)[:-2], schema_id),))
        raw, argument_texts = _split_type(type_name)
        arguments = tuple(self._parse_type(item) for item in argument_texts)
        simple = _raw_type(raw).split(".")[-1]
        if schema_id and argument_texts and simple in {"List", "Set", "Collection", "Iterable", "Optional", "Annotated", "ResponseEntity", "list", "set"}:
            arguments = tuple(self._bind_schema(argument, schema_id) if index == 0 else argument
                              for index, argument in enumerate(arguments))
            schema_id = ""
        elif schema_id and argument_texts and simple in {"Map", "dict"} and len(arguments) > 1:
            arguments = tuple(self._bind_schema(argument, schema_id) if index == 1 else argument
                              for index, argument in enumerate(arguments))
            schema_id = ""
        if not schema_id:
            schema = self._schema_for_type(raw)
            schema_id = schema.id if schema else ""
        return TypeRef(raw, schema_id, arguments)

    @staticmethod
    def _bind_schema(value: TypeRef, schema_id: str) -> TypeRef:
        raw = value.name.split(".")[-1]
        nested_index = 1 if raw in {"Map", "dict"} else 0
        if value.arguments and raw in {"List", "Set", "Collection", "Iterable", "Optional",
                                      "Annotated", "ResponseEntity", "Map", "list", "set", "dict"}:
            return replace(value, arguments=tuple(ApiDocument._bind_schema(item, schema_id)
                           if index == nested_index else item for index, item in enumerate(value.arguments)))
        return replace(value, schema_id=schema_id)

    @staticmethod
    def _substitute(value: TypeRef, bindings: Dict[str, TypeRef]) -> TypeRef:
        if not value.arguments and value.name in bindings:
            return bindings[value.name]
        return replace(value, arguments=tuple(ApiDocument._substitute(item, bindings) for item in value.arguments))

    @staticmethod
    def _with_type(value: Field, type_ref: TypeRef) -> Field:
        return replace(value, type_name=type_ref.display_name(), type_ref=type_ref)

    def with_classes(self, classes: Dict[str, List[Field]]):
        schemas = dict(self.schemas)
        by_name: Dict[str, List[Schema]] = {}
        for schema in schemas.values():
            by_name.setdefault(schema.name, []).append(schema)
        for name, fields in classes.items():
            matches = by_name.get(name, [])
            if len(matches) == 1:
                schemas[matches[0].id] = replace(matches[0], fields=fields)
            elif not matches:
                schema_id = f"{self.language}:{name}"
                schemas[schema_id] = Schema(schema_id, name, name, "", fields)
        return replace(self, schemas=schemas)


def _raw_type(type_name: str) -> str:
    return type_name.strip().replace("? extends ", "").replace("? super ", "")


def _split_type(type_name: str) -> Tuple[str, List[str]]:
    value = _raw_type(type_name)
    start = next((index for index, char in enumerate(value) if char in "<["), -1)
    if start < 0:
        return value, []
    opening, closing = value[start], ">" if value[start] == "<" else "]"
    depth, part_start = 0, start + 1
    for index, char in enumerate(value[start:], start):
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return value[:start].strip(), [part for part in _split_arguments(value[part_start:index]) if part]
    return value, []


def _split_arguments(value: str, separator: str = ",") -> List[str]:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(value):
        if char in "<[":
            depth += 1
        elif char in ">]":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    return parts + [value[start:].strip()]
