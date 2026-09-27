; Supplementary: the upstream tags.scm captures signature declarations only;
; implementation files also declare concrete classes, functions, and enums.
(class_declaration name: (type_identifier) @name) @definition.class
(function_declaration name: (identifier) @name) @definition.function
(enum_declaration name: (identifier) @name) @definition.enum
