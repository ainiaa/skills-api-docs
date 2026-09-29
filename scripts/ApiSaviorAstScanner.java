import com.sun.source.tree.AnnotationTree;
import com.sun.source.tree.AssignmentTree;
import com.sun.source.tree.BinaryTree;
import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.ExpressionTree;
import com.sun.source.tree.ImportTree;
import com.sun.source.tree.LiteralTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.ModifiersTree;
import com.sun.source.tree.NewArrayTree;
import com.sun.source.tree.NewClassTree;
import com.sun.source.tree.ParenthesizedTree;
import com.sun.source.tree.ReturnTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.TreePath;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.TreeScanner;
import com.sun.source.util.Trees;

import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.lang.model.element.Modifier;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/** Java 11 source-only scanner used by the understand-docs Skill. */
public final class ApiSaviorAstScanner {

    private static final Set<String> CONTROLLER_ANNOTATIONS = new HashSet<>(Arrays.asList(
            "Controller", "RestController", "FeignClient"));
    private static final Map<String, String> MAPPING_METHODS = mappingMethods();

    private final Map<String, TypeInfo> types = new LinkedHashMap<>();
    private final List<Endpoint> endpoints = new ArrayList<>();
    private final Set<String> selectedControllers;
    private final Map<String, List<String>> composedMappingMethods = new HashMap<>();
    private final Map<String, ExpressionTree> stringConstants = new HashMap<>();
    private Trees trees;

    private ApiSaviorAstScanner(Set<String> selectedControllers) {
        this.selectedControllers = selectedControllers;
        MAPPING_METHODS.forEach((name, method) -> composedMappingMethods.put(name, Collections.singletonList(method)));
    }

    public static void main(String[] args) throws Exception {
        Arguments arguments = Arguments.parse(args);
        List<Path> files = javaFiles(arguments.sources);
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            throw new IllegalStateException("A JDK is required: javac is not available");
        }
        try (StandardJavaFileManager manager = compiler.getStandardFileManager(null, null, null)) {
            Iterable<? extends JavaFileObject> javaFiles = manager.getJavaFileObjectsFromPaths(files);
            JavacTask task = (JavacTask) compiler.getTask(null, manager, null,
                    Collections.singletonList("-proc:none"), null, javaFiles);
            ApiSaviorAstScanner scanner = new ApiSaviorAstScanner(arguments.controllers);
            scanner.trees = Trees.instance(task);
            List<CompilationUnitTree> units = new ArrayList<>();
            for (CompilationUnitTree unit : task.parse()) {
                units.add(unit);
            }
            for (CompilationUnitTree unit : units) {
                scanner.registerConstants(unit);
            }
            for (CompilationUnitTree unit : units) {
                scanner.registerMappings(unit);
            }
            for (CompilationUnitTree unit : units) {
                scanner.scan(unit);
            }
            scanner.resolveReferences();
            System.out.print(scanner.json());
        }
    }

    private void scan(CompilationUnitTree unit) {
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitClass(ClassTree node, Void unused) {
                processClass(getCurrentPath(), unit, node);
                return super.visitClass(node, unused);
            }
        }.scan(unit, null);
    }

    private void registerMappings(CompilationUnitTree unit) {
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitClass(ClassTree node, Void unused) {
                if (node.getKind() == Tree.Kind.ANNOTATION_TYPE) {
                    String packageName = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
                    String ownerName = qualifiedName(packageName, getCurrentPath());
                    Mapping mapping = mapping(node.getModifiers(), unit, ownerName);
                    if (mapping != null) {
                        composedMappingMethods.put(ownerName, mapping.methods);
                    }
                }
                return super.visitClass(node, unused);
            }
        }.scan(unit, null);
    }

    private void registerConstants(CompilationUnitTree unit) {
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitVariable(VariableTree node, Void unused) {
                if (node.getInitializer() != null && node.getType() != null
                        && "String".equals(simpleType(node.getType().toString()))
                        && node.getModifiers().getFlags().contains(Modifier.FINAL)) {
                    String packageName = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
                    stringConstants.put(qualifiedName(packageName, getCurrentPath().getParentPath())
                            + "." + node.getName(), node.getInitializer());
                }
                return super.visitVariable(node, unused);
            }
        }.scan(unit, null);
    }

    private void processClass(TreePath path, CompilationUnitTree unit, ClassTree node) {
        String typeName = node.getSimpleName().toString();
        if (typeName.isEmpty()) {
            return;
        }
        String packageName = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
        String qualifiedName = qualifiedName(packageName, path);
        List<String> imports = unit.getImports().stream()
                .map(ImportTree::getQualifiedIdentifier).map(Object::toString).collect(Collectors.toList());
        TypeInfo type = new TypeInfo(typeName, qualifiedName, packageName, imports,
                node.getExtendsClause() == null ? "" : node.getExtendsClause().toString(),
                node.getTypeParameters().stream().map(item -> item.getName().toString()).collect(Collectors.toList()));
        type.isEnum = node.getKind() == Tree.Kind.ENUM;
        AnnotationTree ignoredProperties = annotation(node.getModifiers(), "JsonIgnoreProperties");
        Set<String> ignoredNames = new HashSet<>();
        boolean allowGetters = ignoredProperties != null
                && "true".equals(annotationValue(ignoredProperties, "allowGetters", "false"));
        boolean allowSetters = ignoredProperties != null
                && "true".equals(annotationValue(ignoredProperties, "allowSetters", "false"));
        if (ignoredProperties != null) {
            for (ExpressionTree argument : ignoredProperties.getArguments()) {
                ExpressionTree value = argument instanceof AssignmentTree
                        ? ((AssignmentTree) argument).getExpression() : argument;
                if (!(argument instanceof AssignmentTree)
                        || "value".equals(((AssignmentTree) argument).getVariable().toString())) {
                    if (value instanceof NewArrayTree) {
                        for (ExpressionTree item : ((NewArrayTree) value).getInitializers()) {
                            ignoredNames.add(expressionValue(item));
                        }
                    } else {
                        ignoredNames.add(expressionValue(value));
                    }
                }
            }
        }
        type.ignoredNames.addAll(ignoredNames);
        type.allowGetters = allowGetters;
        type.allowSetters = allowSetters;
        for (Tree member : node.getMembers()) {
            if (member instanceof MethodTree) {
                type.methods.add((MethodTree) member);
            }
            if (member instanceof VariableTree) {
                VariableTree variable = (VariableTree) member;
                AnnotationTree jsonIgnore = annotation(variable.getModifiers(), "JsonIgnore");
                if (!type.isEnum && !variable.getModifiers().getFlags().contains(Modifier.STATIC)
                        && !variable.getModifiers().getFlags().contains(Modifier.TRANSIENT)
                        && (jsonIgnore == null || "false".equals(annotationValue(jsonIgnore, "value", "true")))) {
                    Field candidate = field(variable, pathFor(path, member));
                    AnnotationTree property = annotation(variable.getModifiers(), "JsonProperty");
                    candidate.access = property == null ? "" : annotationValue(property, "access", "");
                    if (ignoredNames.contains(candidate.name) || ignoredNames.contains(candidate.wireName)) {
                        if (!allowGetters && !allowSetters) {
                            continue;
                        }
                        if (allowGetters != allowSetters) {
                            candidate.access = allowGetters ? "READ_ONLY" : "WRITE_ONLY";
                        }
                    }
                    type.fields.add(candidate);
                }
            }
        }
        for (MethodTree method : type.methods) {
            if (method.getModifiers().getFlags().contains(Modifier.STATIC)) {
                continue;
            }
            String methodName = method.getName().toString();
            int prefixLength = methodName.startsWith("get") && method.getParameters().isEmpty() ? 3
                    : methodName.startsWith("is") && method.getParameters().isEmpty() ? 2
                    : methodName.startsWith("set") && method.getParameters().size() == 1 ? 3 : 0;
            if (prefixLength == 0 || methodName.length() <= prefixLength) {
                continue;
            }
            String suffix = methodName.substring(prefixLength);
            String propertyName = suffix.length() > 1 && Character.isUpperCase(suffix.charAt(1))
                    ? suffix : Character.toLowerCase(suffix.charAt(0)) + suffix.substring(1);
            Field target = type.fields.stream().filter(item -> item.name.equals(propertyName)).findFirst().orElse(null);
            if (target == null) {
                continue;
            }
            AnnotationTree property = annotation(method.getModifiers(), "JsonProperty");
            AnnotationTree namedAccessor = annotation(method.getModifiers(), prefixLength == 3 && methodName.startsWith("set")
                    ? "JsonSetter" : "JsonGetter");
            AnnotationTree ignored = annotation(method.getModifiers(), "JsonIgnore");
            if (ignored != null && !"false".equals(annotationValue(ignored, "value", "true"))
                    && property == null && target.wireName.isEmpty()) {
                type.fields.remove(target);
                continue;
            }
            AnnotationTree naming = property != null ? property : namedAccessor;
            if (naming != null) {
                String wireName = annotationValue(naming, "value", "");
                if (!wireName.isEmpty()) {
                    target.wireName = wireName;
                }
            }
            if (property != null) {
                String access = annotationValue(property, "access", "");
                if (!access.isEmpty()) {
                    target.access = access;
                }
            }
        }
        if (type.isEnum) {
            type.enumOptions.addAll(enumOptions(node, path));
        }
        types.put(type.id, type);

        if (!isEndpointType(node.getModifiers()) || !isSelected(unit)) {
            return;
        }
        List<String> classPaths = classPaths(node.getModifiers(), unit, type.qualifiedName);
        String classConsumes = firstValue(node.getModifiers(), "consumes");
        for (Tree member : node.getMembers()) {
            if (member instanceof MethodTree) {
                processMethod(unit, pathFor(path, member), (MethodTree) member, classPaths, classConsumes, type);
            }
        }
    }

    private void processMethod(CompilationUnitTree unit, TreePath path, MethodTree method, List<String> classPaths,
                               String classConsumes, TypeInfo owner) {
        Mapping mapping = mapping(method.getModifiers(), unit, owner.qualifiedName);
        if (mapping == null || method.getReturnType() == null) {
            return;
        }
        DocInfo doc = doc(path);
        AnnotationTree operation = annotation(method.getModifiers(), "ApiOperation");
        String title = operation == null ? doc.summary : annotationValue(operation, "value", doc.summary);
        String interfaceNotes = operation == null ? doc.notes : annotationValue(operation, "notes", doc.notes);
        List<ResponseCode> responseCodes = new ArrayList<>(doc.responseCodes);
        AnnotationTree responses = annotation(method.getModifiers(), "ApiResponses");
        AnnotationTree response = annotation(method.getModifiers(), "ApiResponse");
        if (responses != null) {
            new TreeScanner<Void, Void>() {
                @Override
                public Void visitAnnotation(AnnotationTree candidate, Void unused) {
                    if ("ApiResponse".equals(annotationName(candidate))) {
                        responseCodes.add(new ResponseCode(annotationValue(candidate, "code", ""),
                                annotationValue(candidate, "message", "")));
                    }
                    return super.visitAnnotation(candidate, unused);
                }
            }.scan(responses, null);
        } else if (response != null) {
            responseCodes.add(new ResponseCode(annotationValue(response, "code", ""),
                    annotationValue(response, "message", "")));
        }
        List<Field> parameters = new ArrayList<>();
        Field requestBody = null;
        String declaredConsumes = firstValue(method.getModifiers(), "consumes");
        String contentType = mediaType(declaredConsumes.isEmpty() ? classConsumes : declaredConsumes);
        for (VariableTree parameter : method.getParameters()) {
            String rawType = simpleType(parameter.getType().toString()).replace("[]", "");
            if (!hasAnnotation(parameter.getModifiers(), "RequestBody")
                    && !hasAnnotation(parameter.getModifiers(), "RequestParam")
                    && !hasAnnotation(parameter.getModifiers(), "PathVariable")
                    && !hasAnnotation(parameter.getModifiers(), "RequestHeader")
                    && !hasAnnotation(parameter.getModifiers(), "RequestPart")
                    && !hasAnnotation(parameter.getModifiers(), "CookieValue")
                    && Arrays.asList("HttpServletRequest", "HttpServletResponse", "ServletRequest", "ServletResponse",
                            "Principal", "BindingResult", "Model", "ModelMap").contains(rawType)) {
                continue;
            }
            Field field = field(parameter, pathFor(path, parameter));
            field.description = doc.params.getOrDefault(field.name, field.description);
            if (hasAnnotation(parameter.getModifiers(), "RequestBody")) {
                requestBody = field;
                if (contentType.isEmpty()) {
                    contentType = "application/json";
                }
            } else {
                field.location = parameterLocation(parameter);
                String parameterType = simpleType(field.typeName).replace("[]", "");
                boolean filePart = "MultipartFile".equals(parameterType)
                        || (("List".equals(parameterType) || "Collection".equals(parameterType))
                            && "MultipartFile".equals(simpleType(typeArgument(field.typeName, 0))));
                if (filePart) {
                    field.location = "file";
                    contentType = "multipart/form-data";
                } else if ("RequestPart".equals(field.location)) {
                    contentType = "multipart/form-data";
                }
                parameters.add(field);
            }
        }
        if (contentType.isEmpty() && parameters.stream().anyMatch(item -> "query".equals(item.location))
                && !mapping.methods.contains("GET")) {
            contentType = "application/x-www-form-urlencoded";
        }
        if ("application/x-www-form-urlencoded".equals(contentType) || "multipart/form-data".equals(contentType)) {
            for (Field parameter : parameters) {
                if ("query".equals(parameter.location)) {
                    parameter.location = "form";
                }
            }
        }
        int line = (int) unit.getLineMap().getLineNumber(trees.getSourcePositions().getStartPosition(unit, method));
        for (String classPath : classPaths) {
            for (String methodName : mapping.methods) {
                for (String methodPath : mapping.paths) {
                    endpoints.add(new Endpoint(method.getName().toString(), title.isEmpty() ? method.getName().toString() : title,
                            methodName, joinPath(classPath, methodPath), parameters, requestBody,
                            method.getReturnType().toString(), unit.getSourceFile().toUri().getPath() + ":" + line, contentType, owner,
                            interfaceNotes, responseCodes, method));
                }
            }
        }
    }

    private void resolveReferences() {
        for (TypeInfo type : types.values()) {
            type.parentSchemaId = schemaId(type.parent, type);
            for (Field field : type.fields) {
                field.schemaId = schemaId(field.typeName, type);
                field.enumSchemaId = annotationEnumId(field.enumTypeNames, type);
            }
        }
        for (Endpoint endpoint : endpoints) {
            endpoint.responseSchemaId = schemaId(endpoint.responseType, endpoint.owner);
            for (Field parameter : endpoint.parameters) {
                parameter.schemaId = schemaId(parameter.typeName, endpoint.owner);
                parameter.enumSchemaId = annotationEnumId(parameter.enumTypeNames, endpoint.owner);
            }
            if (endpoint.requestBody != null) {
                endpoint.requestBody.schemaId = schemaId(endpoint.requestBody.typeName, endpoint.owner);
                endpoint.requestBody.enumSchemaId = annotationEnumId(endpoint.requestBody.enumTypeNames, endpoint.owner);
            }
            endpoint.enumBindings.addAll(inferEnumBindings(endpoint));
        }
    }

    private List<EnumBinding> inferEnumBindings(Endpoint endpoint) {
        Map<String, Field> sourceParameters = new HashMap<>();
        for (Field parameter : endpoint.parameters) {
            sourceParameters.put(parameter.name, parameter);
        }
        if (endpoint.requestBody != null) {
            sourceParameters.put(endpoint.requestBody.name, endpoint.requestBody);
        }
        Map<String, EnumBinding> found = new LinkedHashMap<>();
        Set<String> ambiguous = new HashSet<>();
        Map<String, String> tracked = new HashMap<>();
        for (String name : sourceParameters.keySet()) {
            tracked.put(name, name);
        }
        inspectEnumCalls(endpoint.methodTree, endpoint.owner, tracked, sourceParameters,
                found, ambiguous, new HashSet<String>());
        return new ArrayList<>(found.values());
    }

    private void inspectEnumCalls(MethodTree method, TypeInfo owner, Map<String, String> tracked,
                                  Map<String, Field> sourceParameters, Map<String, EnumBinding> found,
                                  Set<String> ambiguous, Set<String> visited) {
        if (method == null || method.getBody() == null || tracked.isEmpty()) {
            return;
        }
        String visitKey = owner.id + "#" + method.getName() + tracked.toString();
        if (!visited.add(visitKey)) {
            return;
        }
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitMethodInvocation(MethodInvocationTree call, Void unused) {
                String methodName = callName(call);
                TypeInfo enumType = enumOwner(call, owner);
                if (enumType != null) {
                    for (int index = 0; index < call.getArguments().size(); index++) {
                        ExpressionTree argument = call.getArguments().get(index);
                        if (!(argument instanceof MethodInvocationTree)) {
                            continue;
                        }
                        MethodInvocationTree getter = (MethodInvocationTree) argument;
                        if (!(getter.getMethodSelect() instanceof MemberSelectTree)) {
                            continue;
                        }
                        MemberSelectTree select = (MemberSelectTree) getter.getMethodSelect();
                        String getterName = select.getIdentifier().toString();
                        if (!getterName.startsWith("get") || getterName.length() <= 3
                                || !getter.getArguments().isEmpty()) {
                            continue;
                        }
                        String original = tracked.get(select.getExpression().toString());
                        Field source = sourceParameters.get(original);
                        TypeInfo dto = source == null ? null : types.get(source.schemaId);
                        if (dto == null) {
                            continue;
                        }
                        String fieldName = Character.toLowerCase(getterName.charAt(3)) + getterName.substring(4);
                        Field dtoField = dto.fields.stream().filter(item -> item.name.equals(fieldName)).findFirst().orElse(null);
                        if (dtoField == null || !dtoField.enumSchemaId.isEmpty()) {
                            continue;
                        }
                        String key = original + "#" + dto.id + "#" + fieldName;
                        if (ambiguous.contains(key)) {
                            continue;
                        }
                        EnumBinding binding = new EnumBinding(dto.id, fieldName, enumType.id,
                                parameterName(enumType, methodName, call.getArguments().size(), index), original);
                        EnumBinding previous = found.putIfAbsent(key, binding);
                        if (previous != null && !previous.enumSchemaId.equals(binding.enumSchemaId)) {
                            found.remove(key);
                            ambiguous.add(key);
                        }
                    }
                } else {
                    MethodOwner target = findMethod(owner, call);
                    if (target != null) {
                        Map<String, String> forwarded = new HashMap<>();
                        for (int index = 0; index < call.getArguments().size(); index++) {
                            String original = tracked.get(call.getArguments().get(index).toString());
                            if (original != null) {
                                forwarded.put(target.method.getParameters().get(index).getName().toString(), original);
                            }
                        }
                        inspectEnumCalls(target.method, target.owner, forwarded, sourceParameters,
                                found, ambiguous, visited);
                    }
                }
                return super.visitMethodInvocation(call, unused);
            }
        }.scan(method.getBody(), null);
    }

    private TypeInfo enumOwner(MethodInvocationTree call, TypeInfo context) {
        if (!(call.getMethodSelect() instanceof MemberSelectTree)) {
            return null;
        }
        String typeName = ((MemberSelectTree) call.getMethodSelect()).getExpression().toString();
        TypeInfo candidate = types.get(schemaId(typeName, context));
        return candidate != null && candidate.isEnum ? candidate : null;
    }

    private static String callName(MethodInvocationTree call) {
        if (call.getMethodSelect() instanceof MemberSelectTree) {
            return ((MemberSelectTree) call.getMethodSelect()).getIdentifier().toString();
        }
        return call.getMethodSelect().toString();
    }

    private static String parameterName(TypeInfo type, String name, int arity, int index) {
        MethodTree match = null;
        for (MethodTree method : type.methods) {
            if (method.getName().contentEquals(name) && method.getParameters().size() == arity) {
                if (match != null) {
                    return "";
                }
                match = method;
            }
        }
        return match == null ? "" : match.getParameters().get(index).getName().toString();
    }

    private MethodOwner findMethod(TypeInfo context, MethodInvocationTree call) {
        TypeInfo target = context;
        if (call.getMethodSelect() instanceof MemberSelectTree) {
            String receiver = ((MemberSelectTree) call.getMethodSelect()).getExpression().toString();
            if (!"this".equals(receiver)) {
                target = types.get(schemaId(receiver, context));
                if (target == null) {
                    Field ownerField = context.fields.stream()
                            .filter(field -> field.name.equals(receiver)).findFirst().orElse(null);
                    target = ownerField == null ? null : types.get(ownerField.schemaId);
                }
            }
        }
        if (target == null) {
            return null;
        }
        MethodTree match = null;
        String name = callName(call);
        for (MethodTree method : target.methods) {
            if (method.getName().contentEquals(name) && method.getParameters().size() == call.getArguments().size()) {
                if (match != null) {
                    return null;
                }
                match = method;
            }
        }
        return match == null ? null : new MethodOwner(target, match);
    }

    private String annotationEnumId(List<String> typeNames, TypeInfo context) {
        String found = "";
        for (String name : typeNames) {
            String id = schemaId(name, context);
            TypeInfo candidate = types.get(id);
            if (candidate != null && candidate.isEnum) {
                if (!found.isEmpty() && !found.equals(id)) {
                    return "";
                }
                found = id;
            }
        }
        return found;
    }

    private String schemaId(String typeName, TypeInfo context) {
        String raw = simpleType(typeName).replace("[]", "");
        if (raw.isEmpty() || context == null) {
            return "";
        }
        if ("List".equals(raw) || "Set".equals(raw) || "Collection".equals(raw) || "Iterable".equals(raw)
                || "ResponseEntity".equals(raw) || "Optional".equals(raw)) {
            return schemaId(typeArgument(typeName, 0), context);
        }
        if ("Map".equals(raw)) {
            return schemaId(typeArgument(typeName, 1), context);
        }
        String direct = "java:" + typeName.replace("[]", "").split("<", 2)[0];
        if (types.containsKey(direct)) {
            return direct;
        }
        if (typeName.matches("^[a-z_][\\w]*(?:\\.[\\w]+)+$")) {
            return direct;
        }
        if (typeName.contains(".")) {
            String qualified = context.packageName.isEmpty() ? typeName : context.packageName + "." + typeName;
            if (types.containsKey("java:" + qualified)) {
                return "java:" + qualified;
            }
        }
        for (String imported : context.imports) {
            if (imported.endsWith("." + raw)) {
                return "java:" + imported;
            }
        }
        String samePackage = context.packageName.isEmpty() ? raw : context.packageName + "." + raw;
        if (types.containsKey("java:" + samePackage)) {
            return "java:" + samePackage;
        }
        String match = "";
        for (TypeInfo type : types.values()) {
            if (raw.equals(type.name)) {
                if (!match.isEmpty()) {
                    return "";
                }
                match = type.id;
            }
        }
        return match;
    }

    private static String typeArgument(String typeName, int requested) {
        int start = typeName.indexOf('<');
        if (start < 0) {
            return "";
        }
        int depth = 0;
        int index = 0;
        int partStart = start + 1;
        for (int position = start; position < typeName.length(); position++) {
            char value = typeName.charAt(position);
            if (value == '<') {
                depth++;
            } else if (value == '>') {
                if (--depth == 0) {
                    return index == requested ? typeName.substring(partStart, position).trim() : "";
                }
            } else if (value == ',' && depth == 1) {
                if (index++ == requested) {
                    return typeName.substring(partStart, position).trim();
                }
                partStart = position + 1;
            }
        }
        return "";
    }

    private String qualifiedName(String packageName, TreePath path) {
        List<String> names = new ArrayList<>();
        for (TreePath current = path; current != null; current = current.getParentPath()) {
            if (current.getLeaf() instanceof ClassTree) {
                String name = ((ClassTree) current.getLeaf()).getSimpleName().toString();
                if (!name.isEmpty()) {
                    names.add(0, name);
                }
            }
        }
        String nestedName = String.join(".", names);
        return packageName.isEmpty() ? nestedName : packageName + "." + nestedName;
    }

    private Field field(VariableTree node, TreePath path) {
        DocInfo doc = doc(path);
        Field field = new Field(node.getName().toString(), node.getType().toString());
        AnnotationTree jsonProperty = annotation(node.getModifiers(), "JsonProperty");
        AnnotationTree requestParam = annotation(node.getModifiers(), "RequestParam");
        AnnotationTree pathVariable = annotation(node.getModifiers(), "PathVariable");
        AnnotationTree requestHeader = annotation(node.getModifiers(), "RequestHeader");
        AnnotationTree requestBody = annotation(node.getModifiers(), "RequestBody");
        AnnotationTree requestPart = annotation(node.getModifiers(), "RequestPart");
        AnnotationTree cookieValue = annotation(node.getModifiers(), "CookieValue");
        if (jsonProperty != null) {
            field.wireName = annotationValue(jsonProperty, "value", "");
        } else if (requestParam != null) {
            field.wireName = annotationValue(requestParam, "name", annotationValue(requestParam, "value", ""));
        } else if (pathVariable != null) {
            field.wireName = annotationValue(pathVariable, "name", annotationValue(pathVariable, "value", ""));
        } else if (requestHeader != null) {
            field.wireName = annotationValue(requestHeader, "name", annotationValue(requestHeader, "value", ""));
        } else if (requestPart != null) {
            field.wireName = annotationValue(requestPart, "name", annotationValue(requestPart, "value", ""));
        } else if (cookieValue != null) {
            field.wireName = annotationValue(cookieValue, "name", annotationValue(cookieValue, "value", ""));
        }
        AnnotationTree schema = annotation(node.getModifiers(), "Schema");
        field.description = schema == null ? annotationValue(node.getModifiers(), "value", doc.summary)
                : annotationValue(schema, "description", doc.summary);
        field.notes = firstValue(node.getModifiers(), "notes");
        field.example = firstValue(node.getModifiers(), "example");
        if (field.example.isEmpty()) {
            field.example = null;
        }
        AnnotationTree binding = requestParam != null ? requestParam : pathVariable != null ? pathVariable
                : requestHeader != null ? requestHeader : requestBody != null ? requestBody
                : requestPart != null ? requestPart : cookieValue;
        String defaultValue = binding == null ? null : annotationValue(binding, "defaultValue", null);
        if (field.example == null && defaultValue != null) {
            field.example = defaultValue;
        }
        field.required = hasAnnotation(node.getModifiers(), "NotNull")
                || hasAnnotation(node.getModifiers(), "NotBlank")
                || hasAnnotation(node.getModifiers(), "NotEmpty")
                || (binding != null && defaultValue == null
                    && !"false".equals(annotationValue(binding, "required", "true")))
                || (binding == null && "true".equals(firstValue(node.getModifiers(), "required")));
        if ("Optional".equals(simpleType(field.typeName))) {
            field.required = false;
        }
        if (schema != null) {
            String mode = annotationValue(schema, "requiredMode", "");
            if (mode.endsWith(".REQUIRED") || "REQUIRED".equals(mode)) {
                field.required = true;
            } else if (mode.endsWith(".NOT_REQUIRED") || "NOT_REQUIRED".equals(mode)) {
                field.required = false;
            }
        }
        AnnotationTree minimum = annotation(node.getModifiers(), "Min");
        if (minimum != null) {
            try {
                field.minimum = Long.parseLong(annotationValue(minimum, "value", "").replace("_", "").replaceAll("[lL]$", ""));
                field.notes += (field.notes.isEmpty() ? "" : "；") + "最小值为 " + field.minimum;
            } catch (NumberFormatException ignored) {
                // Leave nonconstant or invalid minimum unresolved.
            }
        }
        for (AnnotationTree annotation : node.getModifiers().getAnnotations()) {
            for (ExpressionTree argument : annotation.getArguments()) {
                String expression = argument instanceof AssignmentTree
                        ? ((AssignmentTree) argument).getExpression().toString() : argument.toString();
                for (String part : expression.split("[{},\\s]+")) {
                    if (part.endsWith(".class")) {
                        field.enumTypeNames.add(part.substring(0, part.length() - 6));
                    }
                }
            }
        }
        return field;
    }

    private List<EnumOption> enumOptions(ClassTree node, TreePath path) {
        List<EnumOption> result = new ArrayList<>();
        String jsonValue = jsonValueProperty(node);
        for (Tree member : node.getMembers()) {
            if (!(member instanceof VariableTree)) {
                continue;
            }
            VariableTree constant = (VariableTree) member;
            if (!(constant.getInitializer() instanceof NewClassTree)
                    || constant.getType() == null
                    || !simpleType(constant.getType().toString()).equals(node.getSimpleName().toString())) {
                continue;
            }
            List<? extends ExpressionTree> arguments = ((NewClassTree) constant.getInitializer()).getArguments();
            MethodTree constructor = matchingConstructor(node, arguments.size());
            Map<String, Object> properties = constructor == null
                    ? Collections.emptyMap() : enumProperties(constructor, arguments);
            String valueKey = property(properties, jsonValue);
            String descriptionKey = property(properties, "description", "desc", "label", "title", "message");
            String referenceKey = property(properties, "value", "code", "key", "id");
            if (referenceKey == null && properties.size() == 1
                    && !properties.keySet().iterator().next().equals(descriptionKey)) {
                referenceKey = properties.keySet().iterator().next();
            }
            Object directValue = null;
            boolean directResolved = false;
            if (jsonValue != null) {
                if (valueKey != null) {
                    directValue = properties.get(valueKey);
                    directResolved = true;
                }
            } else {
                AnnotationTree renamed = annotation(constant.getModifiers(), "JsonProperty");
                if (renamed == null) {
                    renamed = annotation(constant.getModifiers(), "SerializedName");
                }
                directValue = renamed == null ? constant.getName().toString() : annotationValue(renamed, "value", constant.getName().toString());
                directResolved = true;
            }
            Object referenceValue = referenceKey == null ? null : properties.get(referenceKey);
            String description = descriptionKey == null ? doc(pathFor(path, member)).summary
                    : String.valueOf(properties.get(descriptionKey));
            result.add(new EnumOption(constant.getName().toString(), directValue, directResolved,
                    referenceValue, referenceKey != null, description,
                    otherProperties(properties, valueKey, descriptionKey),
                    otherProperties(properties, referenceKey, descriptionKey), properties,
                    descriptionKey == null ? "" : descriptionKey));
        }
        return result;
    }

    private static MethodTree matchingConstructor(ClassTree node, int size) {
        MethodTree result = null;
        for (Tree member : node.getMembers()) {
            if (member instanceof MethodTree) {
                MethodTree method = (MethodTree) member;
                if (method.getReturnType() == null && method.getParameters().size() == size) {
                    if (result != null) {
                        return null;
                    }
                    result = method;
                }
            }
        }
        return result;
    }

    private static Map<String, Object> enumProperties(MethodTree constructor, List<? extends ExpressionTree> arguments) {
        Map<String, String> assignedNames = new HashMap<>();
        if (constructor.getBody() != null) {
            new TreeScanner<Void, Void>() {
                @Override
                public Void visitAssignment(AssignmentTree assignment, Void unused) {
                    String target = assignment.getVariable().toString();
                    if (assignment.getExpression().getKind() == Tree.Kind.IDENTIFIER) {
                        assignedNames.put(assignment.getExpression().toString(), target.substring(target.lastIndexOf('.') + 1));
                    }
                    return super.visitAssignment(assignment, unused);
                }
            }.scan(constructor.getBody(), null);
        }
        Map<String, Object> properties = new LinkedHashMap<>();
        for (int index = 0; index < arguments.size(); index++) {
            String parameter = constructor.getParameters().get(index).getName().toString();
            Object value = literalValue(arguments.get(index));
            if (value != null) {
                String assigned = assignedNames.get(parameter);
                if (assigned != null) {
                    properties.put(assigned, value);
                }
            }
        }
        return properties;
    }

    private static Object literalValue(ExpressionTree expression) {
        if (expression instanceof LiteralTree) {
            return ((LiteralTree) expression).getValue();
        }
        if (expression.getKind() == Tree.Kind.UNARY_MINUS) {
            String value = expression.toString();
            try {
                return Long.parseLong(value);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private static String property(Map<String, Object> properties, String... names) {
        for (String name : names) {
            if (name != null) {
                for (String actual : properties.keySet()) {
                    if (actual.equalsIgnoreCase(name)) {
                        return actual;
                    }
                }
            }
        }
        return null;
    }

    private static String otherProperties(Map<String, Object> properties, String valueKey, String descriptionKey) {
        List<String> result = new ArrayList<>();
        for (Map.Entry<String, Object> property : properties.entrySet()) {
            if (!property.getKey().equals(valueKey) && !property.getKey().equals(descriptionKey)) {
                result.add(property.getKey() + "=" + property.getValue());
            }
        }
        return String.join("；", result);
    }

    private static String jsonValueProperty(ClassTree node) {
        for (Tree member : node.getMembers()) {
            if (member instanceof VariableTree && hasAnnotation(((VariableTree) member).getModifiers(), "JsonValue")) {
                return ((VariableTree) member).getName().toString();
            }
            if (member instanceof MethodTree) {
                MethodTree method = (MethodTree) member;
                if (hasAnnotation(method.getModifiers(), "JsonValue")) {
                    final List<String> returned = new ArrayList<>();
                    if (method.getBody() != null) {
                        new TreeScanner<Void, Void>() {
                            @Override
                            public Void visitReturn(ReturnTree statement, Void unused) {
                                if (statement.getExpression() != null) {
                                    returned.add(statement.getExpression().toString());
                                }
                                return super.visitReturn(statement, unused);
                            }
                        }.scan(method.getBody(), null);
                    }
                    if (returned.size() == 1 && returned.get(0).matches("(?:this\\.)?[A-Za-z_$][\\w$]*")) {
                        String value = returned.get(0);
                        return value.substring(value.lastIndexOf('.') + 1);
                    }
                    return "";
                }
            }
        }
        return null;
    }

    private TreePath pathFor(TreePath parent, Tree child) {
        return new TreePath(parent, child);
    }

    private boolean isSelected(CompilationUnitTree unit) {
        return selectedControllers.isEmpty() || selectedControllers.contains(unit.getSourceFile().toUri().getPath());
    }

    private boolean isEndpointType(ModifiersTree modifiers) {
        for (AnnotationTree annotation : modifiers.getAnnotations()) {
            if (CONTROLLER_ANNOTATIONS.contains(annotationName(annotation))) {
                return true;
            }
        }
        return false;
    }

    private List<String> classPaths(ModifiersTree modifiers, CompilationUnitTree unit, String ownerName) {
        Mapping mapping = mapping(modifiers, unit, ownerName);
        List<String> paths = mapping == null ? Collections.singletonList("") : mapping.paths;
        AnnotationTree feign = annotation(modifiers, "FeignClient");
        if (feign == null) {
            return paths;
        }
        String prefix = mappingValues(feign, "path", null, unit, ownerName).get(0);
        return paths.stream().map(path -> joinPath(prefix, path)).collect(Collectors.toList());
    }

    private Mapping mapping(ModifiersTree modifiers, CompilationUnitTree unit, String ownerName) {
        for (AnnotationTree annotation : modifiers.getAnnotations()) {
            String name = annotationName(annotation);
            String declared = annotation.getAnnotationType().toString();
            String qualified = declared;
            if (!declared.contains(".")) {
                qualified = unit.getImports().stream().map(item -> item.getQualifiedIdentifier().toString())
                        .filter(item -> item.endsWith("." + declared)).findFirst().orElse("");
                if (qualified.isEmpty()) {
                    String packageName = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
                    qualified = packageName.isEmpty() ? declared : packageName + "." + declared;
                }
            }
            List<String> fixedMethods = composedMappingMethods.get(qualified);
            if (fixedMethods == null) {
                fixedMethods = MAPPING_METHODS.containsKey(name)
                        ? Collections.singletonList(MAPPING_METHODS.get(name)) : null;
            }
            if (fixedMethods != null) {
                return new Mapping(fixedMethods, mappingValues(annotation, "path", "value", unit, ownerName));
            }
            if ("RequestMapping".equals(name)) {
                List<String> methods = mappingValues(annotation, "method", null, unit, ownerName);
                if (methods.size() == 1 && methods.get(0).isEmpty()) {
                    methods = Arrays.asList("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE");
                }
                return new Mapping(methods, mappingValues(annotation, "path", "value", unit, ownerName));
            }
        }
        return null;
    }

    private String parameterLocation(VariableTree parameter) {
        if (hasAnnotation(parameter.getModifiers(), "PathVariable")) {
            return "path";
        }
        if (hasAnnotation(parameter.getModifiers(), "RequestHeader")) {
            return "header";
        }
        if (hasAnnotation(parameter.getModifiers(), "RequestPart")) {
            return "RequestPart";
        }
        if (hasAnnotation(parameter.getModifiers(), "CookieValue")) {
            return "cookie";
        }
        return "query";
    }

    private static AnnotationTree annotation(ModifiersTree modifiers, String name) {
        for (AnnotationTree annotation : modifiers.getAnnotations()) {
            if (name.equals(annotationName(annotation))) {
                return annotation;
            }
        }
        return null;
    }

    private static String annotationName(AnnotationTree annotation) {
        String name = annotation.getAnnotationType().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? name : name.substring(dot + 1);
    }

    private static boolean hasAnnotation(ModifiersTree modifiers, String name) {
        return annotation(modifiers, name) != null;
    }

    private static String annotationValue(ModifiersTree modifiers, String key, String fallback) {
        AnnotationTree annotation = annotation(modifiers, "Schema");
        if (annotation == null) {
            annotation = annotation(modifiers, "ApiModelProperty");
        }
        return annotation == null ? fallback : annotationValue(annotation, key, fallback);
    }

    private static String firstValue(ModifiersTree modifiers, String key) {
        for (AnnotationTree annotation : modifiers.getAnnotations()) {
            String value = annotationValue(annotation, key, "");
            if (!value.isEmpty()) {
                return value;
            }
        }
        return "";
    }

    private static String annotationValue(AnnotationTree annotation, String key, String fallback) {
        for (ExpressionTree argument : annotation.getArguments()) {
            if (argument instanceof AssignmentTree) {
                AssignmentTree assignment = (AssignmentTree) argument;
                if (key.equals(assignment.getVariable().toString())) {
                    return expressionValue(assignment.getExpression());
                }
            } else if ("value".equals(key)) {
                return expressionValue(argument);
            }
        }
        return fallback;
    }

    private List<String> mappingValues(AnnotationTree annotation, String key, String alternative,
                                       CompilationUnitTree unit, String ownerName) {
        for (ExpressionTree argument : annotation.getArguments()) {
            ExpressionTree expression = argument;
            String argumentKey = "value";
            if (argument instanceof AssignmentTree) {
                AssignmentTree assignment = (AssignmentTree) argument;
                argumentKey = assignment.getVariable().toString();
                expression = assignment.getExpression();
            }
            if (key.equals(argumentKey) || alternative != null && alternative.equals(argumentKey)) {
                if (expression instanceof NewArrayTree) {
                    List<String> values = new ArrayList<>();
                    for (ExpressionTree initializer : ((NewArrayTree) expression).getInitializers()) {
                        values.add("method".equals(key) ? expressionValue(initializer)
                                : routeValue(initializer, unit, ownerName, new HashSet<String>()));
                    }
                    return values.isEmpty() ? Collections.singletonList("") : values;
                }
                return Collections.singletonList("method".equals(key) ? expressionValue(expression)
                        : routeValue(expression, unit, ownerName, new HashSet<String>()));
            }
        }
        return Collections.singletonList("");
    }

    private String routeValue(ExpressionTree expression, CompilationUnitTree unit, String ownerName, Set<String> seen) {
        if (expression instanceof LiteralTree) {
            Object value = ((LiteralTree) expression).getValue();
            return value == null ? "" : String.valueOf(value);
        }
        if (expression instanceof ParenthesizedTree) {
            return routeValue(((ParenthesizedTree) expression).getExpression(), unit, ownerName, seen);
        }
        if (expression instanceof BinaryTree && expression.getKind() == Tree.Kind.PLUS) {
            BinaryTree binary = (BinaryTree) expression;
            return routeValue(binary.getLeftOperand(), unit, ownerName, new HashSet<>(seen))
                    + routeValue(binary.getRightOperand(), unit, ownerName, new HashSet<>(seen));
        }
        String name = expression.toString();
        String packageName = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
        String direct = stringConstants.containsKey(ownerName + "." + name) ? ownerName + "." + name
                : stringConstants.containsKey(name) ? name : packageName + "." + name;
        if (!stringConstants.containsKey(direct) && name.contains(".")) {
            String first = name.substring(0, name.indexOf('.'));
            String suffix = name.substring(name.indexOf('.'));
            for (ImportTree item : unit.getImports()) {
                String imported = item.getQualifiedIdentifier().toString();
                if (imported.endsWith("." + first) && stringConstants.containsKey(imported + suffix)) {
                    direct = imported + suffix;
                    break;
                }
            }
        }
        if (!stringConstants.containsKey(direct) && !name.contains(".")) {
            for (ImportTree item : unit.getImports()) {
                String imported = item.getQualifiedIdentifier().toString();
                if (item.isStatic() && imported.endsWith("." + name) && stringConstants.containsKey(imported)) {
                    direct = imported;
                    break;
                }
            }
        }
        if (!stringConstants.containsKey(direct)) {
            List<String> matches = stringConstants.keySet().stream()
                    .filter(item -> item.endsWith("." + name)).collect(Collectors.toList());
            if (matches.size() != 1) {
                throw new IllegalArgumentException("Unresolved or ambiguous route constant: " + name);
            }
            direct = matches.get(0);
        }
        if (!seen.add(direct)) {
            throw new IllegalArgumentException("Cyclic route constant: " + direct);
        }
        return routeValue(stringConstants.get(direct), unit, ownerName, seen);
    }

    private static String expressionValue(ExpressionTree expression) {
        if (expression instanceof NewArrayTree) {
            List<String> values = new ArrayList<>();
            for (ExpressionTree initializer : ((NewArrayTree) expression).getInitializers()) {
                values.add(expressionValue(initializer));
            }
            return String.join("/", values);
        }
        if (expression instanceof LiteralTree) {
            Object value = ((LiteralTree) expression).getValue();
            return value == null ? "" : String.valueOf(value);
        }
        String value = expression.toString();
        int dot = value.lastIndexOf('.');
        return dot < 0 ? value : value.substring(dot + 1);
    }

    private static String mediaType(String value) {
        if ("APPLICATION_JSON_VALUE".equals(value)) {
            return "application/json";
        }
        if ("APPLICATION_XML_VALUE".equals(value)) {
            return "application/xml";
        }
        if ("MULTIPART_FORM_DATA_VALUE".equals(value)) {
            return "multipart/form-data";
        }
        if ("APPLICATION_FORM_URLENCODED_VALUE".equals(value)) {
            return "application/x-www-form-urlencoded";
        }
        return value;
    }

    private DocInfo doc(TreePath path) {
        String comment = trees.getDocComment(path);
        if (comment == null) {
            return new DocInfo("", "", Collections.<String, String>emptyMap(), Collections.<ResponseCode>emptyList());
        }
        List<String> summary = new ArrayList<>();
        List<String> notes = new ArrayList<>();
        Map<String, String> parameters = new HashMap<>();
        List<ResponseCode> responseCodes = new ArrayList<>();
        for (String raw : comment.split("\\R")) {
            String line = raw.trim();
            if (line.startsWith("@param")) {
                String[] values = line.split("\\s+", 3);
                if (values.length > 2) {
                    parameters.put(values[1], values[2]);
                }
            } else if (line.startsWith("@notes ") || line.startsWith("#notes ")) {
                notes.add(line.substring(7).trim());
            } else if (line.startsWith("@code ") || line.startsWith("#code ")) {
                String[] values = line.substring(6).trim().split("\\s+", 2);
                if (values.length > 0) {
                    responseCodes.add(new ResponseCode(values[0], values.length > 1 ? values[1] : ""));
                }
            } else if (!line.startsWith("@")) {
                summary.add(line);
            }
        }
        return new DocInfo(String.join(" ", summary).trim(), String.join(" ", notes), parameters, responseCodes);
    }

    private String json() {
        StringBuilder output = new StringBuilder("{\"endpoints\":[");
        for (int index = 0; index < endpoints.size(); index++) {
            if (index > 0) {
                output.append(',');
            }
            appendEndpoint(output, endpoints.get(index));
        }
        output.append("],\"ir_version\":1,\"language\":\"java\",\"framework\":\"spring\",\"schemas\":[");
        int index = 0;
        for (Map.Entry<String, TypeInfo> entry : types.entrySet()) {
            if (index++ > 0) {
                output.append(',');
            }
            TypeInfo type = entry.getValue();
            output.append('{');
            property(output, "id", type.id).append(',');
            property(output, "name", type.name).append(',');
            property(output, "qualified_name", type.qualifiedName).append(',');
            property(output, "parent", type.parent).append(",\"fields\":[");
            appendFields(output, entry.getValue().fields);
            output.append("],\"parent_schema_id\":");
            quote(output, type.parentSchemaId).append(",\"type_parameters\":[");
            for (int parameter = 0; parameter < type.typeParameters.size(); parameter++) {
                if (parameter > 0) {
                    output.append(',');
                }
                quote(output, type.typeParameters.get(parameter));
            }
            output.append("],\"ignored_properties\":[");
            int ignoredIndex = 0;
            for (String ignoredName : type.ignoredNames) {
                if (ignoredIndex++ > 0) {
                    output.append(',');
                }
                quote(output, ignoredName);
            }
            output.append("],\"allow_getters\":").append(type.allowGetters);
            output.append(",\"allow_setters\":").append(type.allowSetters);
            output.append(",\"enum_options\":[");
            for (int option = 0; option < type.enumOptions.size(); option++) {
                if (option > 0) {
                    output.append(',');
                }
                appendEnumOption(output, type.enumOptions.get(option));
            }
            output.append("]}");
        }
        return output.append("]}").toString();
    }

    private static void appendEndpoint(StringBuilder output, Endpoint endpoint) {
        output.append('{');
        property(output, "name", endpoint.name).append(',');
        property(output, "notes", endpoint.notes).append(',');
        property(output, "method", endpoint.method).append(',');
        property(output, "path", endpoint.path).append(',');
        property(output, "response_type", endpoint.responseType).append(',');
        property(output, "response_schema_id", endpoint.responseSchemaId).append(',');
        property(output, "source", endpoint.source).append(',');
        property(output, "content_type", endpoint.contentType).append(',');
        property(output, "interface_notes", endpoint.interfaceNotes).append(",\"response_codes\":[");
        for (int index = 0; index < endpoint.responseCodes.size(); index++) {
            if (index > 0) {
                output.append(',');
            }
            ResponseCode responseCode = endpoint.responseCodes.get(index);
            output.append('{');
            property(output, "code", responseCode.code).append(',');
            property(output, "message", responseCode.message).append('}');
        }
        output.append("],\"enum_bindings\":[");
        for (int index = 0; index < endpoint.enumBindings.size(); index++) {
            if (index > 0) {
                output.append(',');
            }
            EnumBinding binding = endpoint.enumBindings.get(index);
            output.append('{');
            property(output, "schema_id", binding.schemaId).append(',');
            property(output, "field_name", binding.fieldName).append(',');
            property(output, "enum_schema_id", binding.enumSchemaId).append(',');
            property(output, "value_hint", binding.valueHint).append(',');
            property(output, "parameter_name", binding.parameterName).append('}');
        }
        output.append("],\"parameters\":[");
        appendFields(output, endpoint.parameters);
        output.append("],\"request_body\":");
        if (endpoint.requestBody == null) {
            output.append("null");
        } else {
            appendField(output, endpoint.requestBody);
        }
        output.append('}');
    }

    private static void appendFields(StringBuilder output, List<Field> fields) {
        for (int index = 0; index < fields.size(); index++) {
            if (index > 0) {
                output.append(',');
            }
            appendField(output, fields.get(index));
        }
    }

    private static void appendField(StringBuilder output, Field field) {
        output.append('{');
        property(output, "name", field.name).append(',');
        property(output, "type_name", field.typeName).append(',');
        property(output, "description", field.description).append(',');
        output.append("\"required\":").append(field.required).append(',');
        property(output, "notes", field.notes).append(',');
        output.append("\"example\":");
        appendJsonValue(output, field.example);
        output.append(',');
        property(output, "location", field.location).append(',');
        property(output, "schema_id", field.schemaId).append(',');
        property(output, "enum_schema_id", field.enumSchemaId).append(',');
        output.append("\"minimum\":");
        appendJsonValue(output, field.minimum);
        output.append(',');
        property(output, "enum_value_hint", field.enumValueHint).append(',');
        property(output, "wire_name", field.wireName).append(',');
        property(output, "access", field.access).append('}');
    }

    private static void appendEnumOption(StringBuilder output, EnumOption option) {
        output.append('{');
        property(output, "member_name", option.memberName).append(',');
        output.append("\"api_value\":");
        appendJsonValue(output, option.apiValue);
        output.append(',');
        property(output, "description", option.description).append(',');
        property(output, "attributes", option.attributes).append(',');
        property(output, "reference_attributes", option.referenceAttributes).append(',');
        property(output, "description_property", option.descriptionProperty).append(',');
        output.append("\"properties\":{");
        int propertyIndex = 0;
        for (Map.Entry<String, Object> entry : option.properties.entrySet()) {
            if (propertyIndex++ > 0) {
                output.append(',');
            }
            quote(output, entry.getKey()).append(':');
            appendJsonValue(output, entry.getValue());
        }
        output.append("},");
        output.append("\"value_resolved\":").append(option.valueResolved).append(',');
        output.append("\"reference_value\":");
        appendJsonValue(output, option.referenceValue);
        output.append(",\"reference_resolved\":").append(option.referenceResolved).append('}');
    }

    private static void appendJsonValue(StringBuilder output, Object value) {
        if (value == null) {
            output.append("null");
        } else if (value instanceof Number || value instanceof Boolean) {
            output.append(value);
        } else {
            quote(output, String.valueOf(value));
        }
    }

    private static StringBuilder property(StringBuilder output, String name, String value) {
        quote(output, name).append(':');
        return quote(output, value);
    }

    private static StringBuilder quote(StringBuilder output, String value) {
        output.append('"');
        for (char character : value.toCharArray()) {
            switch (character) {
                case '\\': output.append("\\\\"); break;
                case '"': output.append("\\\""); break;
                case '\n': output.append("\\n"); break;
                case '\r': output.append("\\r"); break;
                case '\t': output.append("\\t"); break;
                default:
                    if (character < 0x20) {
                        output.append(String.format("\\u%04x", (int) character));
                    } else {
                        output.append(character);
                    }
            }
        }
        return output.append('"');
    }

    private static String joinPath(String left, String right) {
        String path = (left + "/" + right).replaceAll("/+", "/");
        return path.startsWith("/") ? path : "/" + path;
    }

    private static String simpleType(String type) {
        int generic = type.indexOf('<');
        String raw = generic < 0 ? type : type.substring(0, generic);
        int dot = raw.lastIndexOf('.');
        return dot < 0 ? raw.trim() : raw.substring(dot + 1).trim();
    }

    private static Map<String, String> mappingMethods() {
        Map<String, String> mappings = new HashMap<>();
        mappings.put("GetMapping", "GET");
        mappings.put("PostMapping", "POST");
        mappings.put("PutMapping", "PUT");
        mappings.put("PatchMapping", "PATCH");
        mappings.put("DeleteMapping", "DELETE");
        return mappings;
    }

    private static List<Path> javaFiles(List<Path> sources) throws IOException {
        List<Path> result = new ArrayList<>();
        for (Path source : sources) {
            if (Files.isRegularFile(source) && source.toString().endsWith(".java")) {
                result.add(source);
            } else if (Files.isDirectory(source)) {
                try (Stream<Path> paths = Files.walk(source)) {
                    result.addAll(paths.filter(path -> path.toString().endsWith(".java")).collect(Collectors.toList()));
                }
            }
        }
        return result;
    }

    private static final class Arguments {
        private final List<Path> sources = new ArrayList<>();
        private final Set<String> controllers = new HashSet<>();

        private static Arguments parse(String[] values) {
            Arguments arguments = new Arguments();
            for (int index = 0; index < values.length; index++) {
                if ("--source".equals(values[index]) && ++index < values.length) {
                    arguments.sources.add(Paths.get(values[index]).toAbsolutePath());
                } else if ("--controller".equals(values[index]) && ++index < values.length) {
                    arguments.controllers.add(Paths.get(values[index]).toAbsolutePath().toUri().getPath());
                } else {
                    throw new IllegalArgumentException("Expected --source or --controller path");
                }
            }
            if (arguments.sources.isEmpty()) {
                throw new IllegalArgumentException("At least one --source is required");
            }
            return arguments;
        }
    }

    private static final class TypeInfo {
        private final String id;
        private final String name;
        private final String qualifiedName;
        private final String packageName;
        private final List<String> imports;
        private final String parent;
        private final List<String> typeParameters;
        private String parentSchemaId = "";
        private final List<Field> fields = new ArrayList<>();
        private final List<MethodTree> methods = new ArrayList<>();
        private final Set<String> ignoredNames = new HashSet<>();
        private boolean allowGetters;
        private boolean allowSetters;
        private boolean isEnum;
        private final List<EnumOption> enumOptions = new ArrayList<>();

        private TypeInfo(String name, String qualifiedName, String packageName, List<String> imports, String parent,
                         List<String> typeParameters) {
            this.id = "java:" + qualifiedName;
            this.name = name;
            this.qualifiedName = qualifiedName;
            this.packageName = packageName;
            this.imports = imports;
            this.parent = parent;
            this.typeParameters = typeParameters;
        }
    }

    private static final class Mapping {
        private final List<String> methods;
        private final List<String> paths;

        private Mapping(List<String> methods, List<String> paths) {
            this.methods = methods;
            this.paths = paths;
        }
    }

    private static final class DocInfo {
        private final String summary;
        private final String notes;
        private final Map<String, String> params;
        private final List<ResponseCode> responseCodes;

        private DocInfo(String summary, String notes, Map<String, String> params, List<ResponseCode> responseCodes) {
            this.summary = summary;
            this.notes = notes;
            this.params = params;
            this.responseCodes = responseCodes;
        }
    }

    private static final class ResponseCode {
        private final String code;
        private final String message;

        private ResponseCode(String code, String message) {
            this.code = code;
            this.message = message;
        }
    }

    private static final class MethodOwner {
        private final TypeInfo owner;
        private final MethodTree method;

        private MethodOwner(TypeInfo owner, MethodTree method) {
            this.owner = owner;
            this.method = method;
        }
    }

    private static final class EnumBinding {
        private final String schemaId;
        private final String fieldName;
        private final String enumSchemaId;
        private final String valueHint;
        private final String parameterName;

        private EnumBinding(String schemaId, String fieldName, String enumSchemaId, String valueHint,
                            String parameterName) {
            this.schemaId = schemaId;
            this.fieldName = fieldName;
            this.enumSchemaId = enumSchemaId;
            this.valueHint = valueHint;
            this.parameterName = parameterName;
        }
    }

    private static final class Field {
        private final String name;
        private final String typeName;
        private String description = "";
        private boolean required;
        private String notes = "";
        private String example = "";
        private String location = "";
        private String schemaId = "";
        private String enumSchemaId = "";
        private Long minimum;
        private String enumValueHint = "";
        private String wireName = "";
        private String access = "";
        private final List<String> enumTypeNames = new ArrayList<>();

        private Field(String name, String typeName) {
            this.name = name;
            this.typeName = typeName;
        }
    }

    private static final class EnumOption {
        private final String memberName;
        private final Object apiValue;
        private final boolean valueResolved;
        private final Object referenceValue;
        private final boolean referenceResolved;
        private final String description;
        private final String attributes;
        private final String referenceAttributes;
        private final Map<String, Object> properties;
        private final String descriptionProperty;

        private EnumOption(String memberName, Object apiValue, boolean valueResolved,
                           Object referenceValue, boolean referenceResolved, String description, String attributes,
                           String referenceAttributes, Map<String, Object> properties, String descriptionProperty) {
            this.memberName = memberName;
            this.apiValue = apiValue;
            this.valueResolved = valueResolved;
            this.referenceValue = referenceValue;
            this.referenceResolved = referenceResolved;
            this.description = description;
            this.attributes = attributes;
            this.referenceAttributes = referenceAttributes;
            this.properties = properties;
            this.descriptionProperty = descriptionProperty;
        }
    }

    private static final class Endpoint {
        private final String name;
        private final String notes;
        private final String method;
        private final String path;
        private final List<Field> parameters;
        private final Field requestBody;
        private final String responseType;
        private final String source;
        private final String contentType;
        private final TypeInfo owner;
        private String responseSchemaId = "";
        private final String interfaceNotes;
        private final List<ResponseCode> responseCodes;
        private final MethodTree methodTree;
        private final List<EnumBinding> enumBindings = new ArrayList<>();

        private Endpoint(String name, String notes, String method, String path, List<Field> parameters,
                         Field requestBody, String responseType, String source, String contentType, TypeInfo owner,
                         String interfaceNotes, List<ResponseCode> responseCodes, MethodTree methodTree) {
            this.name = name;
            this.notes = notes;
            this.method = method;
            this.path = path;
            this.parameters = parameters;
            this.requestBody = requestBody;
            this.responseType = responseType;
            this.source = source;
            this.contentType = contentType;
            this.owner = owner;
            this.interfaceNotes = interfaceNotes;
            this.responseCodes = responseCodes;
            this.methodTree = methodTree;
        }
    }
}
