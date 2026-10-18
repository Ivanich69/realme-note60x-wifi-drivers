"""Use the local pinned libclang only to select AST roots for JSON dumping.

Final type/probe comparisons still use the pinned clang executable. Selection
keeps every main-file function/global with a direct function reference in a
callback-valued call/assignment/initializer, plus timer/work inline wrappers.
"""

import ctypes as c
import os
from pathlib import Path


class CXString(c.Structure):
    _fields_ = [('data', c.c_void_p), ('flags', c.c_uint)]


class Cursor(c.Structure):
    _fields_ = [('kind', c.c_uint), ('xdata', c.c_int), ('data', c.c_void_p * 3)]


class Type(c.Structure):
    _fields_ = [('kind', c.c_uint), ('data', c.c_void_p * 2)]


class Location(c.Structure):
    _fields_ = [('data', c.c_void_p * 2), ('offset', c.c_uint)]


VISITOR = c.CFUNCTYPE(c.c_uint, Cursor, Cursor, c.c_void_p)


class Clang:
    def __init__(self, library):
        self.api = c.CDLL(str(library))
        functions = {
            'createIndex': (c.c_void_p, [c.c_int, c.c_int]),
            'disposeIndex': (None, [c.c_void_p]),
            'parseTranslationUnit2': (c.c_int, [c.c_void_p, c.c_char_p, c.POINTER(c.c_char_p), c.c_int, c.c_void_p, c.c_uint, c.c_uint, c.POINTER(c.c_void_p)]),
            'disposeTranslationUnit': (None, [c.c_void_p]),
            'getTranslationUnitCursor': (Cursor, [c.c_void_p]),
            'visitChildren': (c.c_uint, [Cursor, VISITOR, c.c_void_p]),
            'getCursorSpelling': (CXString, [Cursor]),
            'getCursorLocation': (Location, [Cursor]),
            'getSpellingLocation': (None, [Location, c.POINTER(c.c_void_p), c.POINTER(c.c_uint), c.POINTER(c.c_uint), c.POINTER(c.c_uint)]),
            'getFileName': (CXString, [c.c_void_p]),
            'getCursorType': (Type, [Cursor]),
            'getCanonicalType': (Type, [Type]),
            'getTypeSpelling': (CXString, [Type]),
            'getCursorReferenced': (Cursor, [Cursor]),
            'Cursor_getNumArguments': (c.c_int, [Cursor]),
            'Cursor_getArgument': (Cursor, [Cursor, c.c_uint]),
            'getCString': (c.c_char_p, [CXString]),
            'disposeString': (None, [CXString]),
            'getNumDiagnostics': (c.c_uint, [c.c_void_p]),
            'getDiagnostic': (c.c_void_p, [c.c_void_p, c.c_uint]),
            'getDiagnosticSeverity': (c.c_uint, [c.c_void_p]),
            'formatDiagnostic': (CXString, [c.c_void_p, c.c_uint]),
            'disposeDiagnostic': (None, [c.c_void_p]),
        }
        for name, (result, args) in functions.items():
            fn = getattr(self.api, 'clang_' + name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)

    def string(self, value):
        result = self.getCString(value)
        text = result.decode(errors='replace') if result else ''
        self.disposeString(value)
        return text

    def children(self, cursor):
        values = []
        @VISITOR
        def visitor(child, parent, unused):
            values.append(child)
            return 1
        self.visitChildren(cursor, visitor, None)
        return values

    def filename(self, cursor):
        file = c.c_void_p()
        self.getSpellingLocation(self.getCursorLocation(cursor), c.byref(file), None, None, None)
        return self.string(self.getFileName(file)) if file else ''

    def type_name(self, cursor):
        return self.string(self.getTypeSpelling(self.getCanonicalType(self.getCursorType(cursor))))

    def function_ref(self, cursor):
        if cursor.kind == 101 and self.getCursorReferenced(cursor).kind == 8:
            return True
        return any(self.function_ref(child) for child in self.children(cursor))

    def targets(self, cursor):
        # A function called to produce a value is not the callback address.
        if cursor.kind == 103:
            return []
        if cursor.kind == 101:
            target = self.getCursorReferenced(cursor)
            if target.kind == 8:
                return [target]
        values = []
        for child in self.children(cursor):
            values.extend(self.targets(child))
        return values

    def collect(self, cursor, owner):
        records, requires_json = [], False

        def add(value, expected, context):
            targets = self.targets(value)
            targets = {self.string(self.getCursorSpelling(target)): target for target in targets}
            if len(targets) != 1 or '(*)(' not in expected:
                return
            name, target = next(iter(targets.items()))
            records.append({'context': context, 'contexts': [context], 'expected_type': expected,
                            'function': name, 'declared_type': self.type_name(target),
                            'location': {'file': self.filename(value)}, 'owner': owner,
                            'AST_provider': 'pinned libclang; canonical types'})

        def visit(node):
            nonlocal requires_json
            children = self.children(node)
            if node.kind == 119 and self.function_ref(node):
                requires_json = True
            if node.kind == 103:
                target = self.getCursorReferenced(node)
                if target.kind == 8:
                    name = self.string(self.getCursorSpelling(target))
                    params = [p for p in self.children(target) if p.kind == 10]
                    for index in range(self.Cursor_getNumArguments(node)):
                        expected = self.type_name(params[index]) if index < len(params) else ''
                        if name in ('rtw_init_timer', '_init_timer') and index == 2:
                            expected = 'void (*)(void *)'
                        if name == '_init_workitem' and index == 1:
                            expected = 'void (*)(struct work_struct *)'
                        add(self.Cursor_getArgument(node, index), expected, f'call:{name}:arg{index}')
            elif node.kind == 114 and len(children) == 2:
                field = self.string(self.getCursorSpelling(children[0]))
                add(children[1], self.type_name(children[0]), 'binary:' + field)
            for child in children:
                visit(child)
        visit(cursor)
        return records, requires_json

    def has_registration(self, cursor):
        children = self.children(cursor)
        if cursor.kind == 103:  # CallExpr
            target = self.getCursorReferenced(cursor)
            name = self.string(self.getCursorSpelling(target))
            params = [p for p in self.children(target) if p.kind == 10] if target.kind == 8 else []
            arguments = children[1:]
            for index, argument in enumerate(arguments):
                expected = self.type_name(params[index]) if index < len(params) else ''
                special = (name in ('rtw_init_timer', '_init_timer') and index == 2) or (name == '_init_workitem' and index == 1)
                if ('(*)(' in expected or '(*' in expected or special) and self.function_ref(argument):
                    return True
        if cursor.kind == 114 and len(children) == 2:  # BinaryOperator
            if '(*' in self.type_name(children[0]) and self.function_ref(children[1]):
                return True
        if cursor.kind == 119 and self.function_ref(cursor):  # InitListExpr
            return True
        return any(self.has_registration(child) for child in children)

    def roots(self, source, flags, directory):
        previous = os.getcwd()
        os.chdir(directory)
        index, tu = self.createIndex(0, 0), c.c_void_p()
        try:
            encoded = [str(flag).encode() for flag in flags]
            args = (c.c_char_p * len(encoded))(*encoded)
            status = self.parseTranslationUnit2(index, str(source).encode(), args, len(encoded), None, 0, 0, c.byref(tu))
            assert status == 0 and tu, f'libclang parse failed: {status}'
            for number in range(self.getNumDiagnostics(tu)):
                diagnostic = self.getDiagnostic(tu, number)
                try:
                    assert self.getDiagnosticSeverity(diagnostic) < 3, self.string(self.formatDiagnostic(diagnostic, 0))
                finally:
                    self.disposeDiagnostic(diagnostic)
            roots, declarations, records = [], {}, []
            for cursor in self.children(self.getTranslationUnitCursor(tu)):
                name = self.string(self.getCursorSpelling(cursor))
                if cursor.kind == 8:
                    params = [self.type_name(child) for child in self.children(cursor) if child.kind == 10]
                    declarations['function:' + name] = {'kind': 'FunctionDecl', 'name': name,
                        'inner': [{'kind': 'ParmVarDecl', 'type': {'qualType': value}} for value in params]}
                elif cursor.kind == 2 and name:
                    fields = [child for child in self.children(cursor) if child.kind == 6]
                    if fields:
                        declarations['record:' + name] = {'kind': 'RecordDecl', 'name': name, 'completeDefinition': True,
                            'inner': [{'kind': 'FieldDecl', 'name': self.string(self.getCursorSpelling(field)),
                                       'type': {'qualType': self.type_name(field)}} for field in fields]}
                if cursor.kind not in (8, 9):
                    continue
                if self.filename(cursor).startswith(str(source).split('/drivers/')[0] + '/drivers/'):
                    direct, needs_json = self.collect(cursor, name)
                    if needs_json:
                        roots.append(name)
                    else:
                        records.extend(direct)
            return sorted(set(roots)), declarations, records
        finally:
            if tu:
                self.disposeTranslationUnit(tu)
            self.disposeIndex(index)
            os.chdir(previous)
