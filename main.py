import glob
import re
import sys
import typing
from dataclasses import dataclass, field
from typing import TextIO, List, Dict, Set

from clang import cindex

COMMON_DECL_KINDS = [
    cindex.CursorKind.STRUCT_DECL,
    cindex.CursorKind.UNION_DECL,
    cindex.CursorKind.CLASS_DECL,
    cindex.CursorKind.ENUM_DECL,
    cindex.CursorKind.FUNCTION_DECL,
    cindex.CursorKind.TYPEDEF_DECL,
    cindex.CursorKind.FUNCTION_TEMPLATE,
    cindex.CursorKind.CLASS_TEMPLATE,
    cindex.CursorKind.NAMESPACE_ALIAS,
    # cindex.CursorKind.USING_DECLARATION,
    cindex.CursorKind.TYPE_ALIAS_DECL,
]


@dataclass
class ExportedNameMap:
    top_level: Set[str] = field(default_factory=set)
    qualified: Dict[str, 'ExportedNameMap'] = field(default_factory=dict)


def generate_exports_from_name_map(name_map: ExportedNameMap, out: TextIO):
    fqn_prefix_stack = ['::']

    # noinspection PyShadowingNames
    def _generate_exports_impl(name_map: ExportedNameMap):
        fqn_prefix = fqn_prefix_stack[-1]
        for name in sorted(name_map.top_level, key=str.lower):
            out.write(f'using {fqn_prefix}{name};\n')
        for namespace, inner_map in sorted(name_map.qualified.items(), key=lambda name_to_map: name_to_map[0].lower()):
            out.write(f'namespace {namespace} {{\n')
            fqn_prefix_stack.append(f'{fqn_prefix}{namespace}::')
            _generate_exports_impl(inner_map)
            fqn_prefix_stack.pop()
            out.write('}\n')

    out.write('export {\n')
    _generate_exports_impl(name_map)
    out.write('}')


class ExportedNamesCollector:
    _IDENTIFIER_REGEX = re.compile(r'(^[a-zA-Z_][a-zA-Z0-9_]*$|^operator\b)')

    only_names_from_path: str

    _name_map_stack: List[ExportedNameMap]

    _include_paths_regex: typing.Pattern
    _ignored_namespaces_regex: typing.Pattern
    _ignored_names_regex: typing.Pattern

    def __init__(self, *,
                 include_paths_regex: str = r'.*',
                 ignored_namespaces_regex: str = r'(^_|^(std|[Dd]etails?|[Pp]rivate|[Ii]mpl|[Ii]ntern(al)?)$)',
                 ignored_names_regex: str = r'(^_|(^[Ii]mpl|[_0-9]impl|[a-z0-9_]Impl)$)'):
        self._include_paths_regex = re.compile(include_paths_regex)
        self._name_map_stack = [ExportedNameMap()]
        self._ignored_namespaces_regex = re.compile(ignored_namespaces_regex)
        self._ignored_names_regex = re.compile(ignored_names_regex)

    def get_collected_names(self) -> ExportedNameMap:
        return self._name_map_stack[0]

    def collect_names(self, translation_unit: cindex.TranslationUnit):
        cursor = translation_unit.cursor
        self._traverse_children(cursor)

    def _traverse(self, cursor: cindex.Cursor):
        if not cursor.kind.is_declaration() or not self._include_paths_regex.search(cursor.location.file.name):
            return

        if cursor.kind == cindex.CursorKind.NAMESPACE or cursor.kind in COMMON_DECL_KINDS:
            if not ExportedNamesCollector._IDENTIFIER_REGEX.search(cursor.spelling):
                return

            current_name_map = self._name_map_stack[-1]

            if cursor.kind == cindex.CursorKind.NAMESPACE:
                if self._ignored_namespaces_regex.search(cursor.spelling):
                    return

                if cursor.spelling not in current_name_map.qualified:
                    current_name_map.qualified[cursor.spelling] = ExportedNameMap()

                self._name_map_stack.append(current_name_map.qualified[cursor.spelling])
                self._traverse_children(cursor)
                self._name_map_stack.pop()

            else:
                if self._ignored_names_regex.search(cursor.spelling):
                    return

                current_name_map.top_level.add(cursor.spelling)

            return

        # Default case: just recurse into children
        self._traverse_children(cursor)

    def _traverse_children(self, cursor: cindex.Cursor):
        for child in cursor.get_children():
            self._traverse(child)


def main(_prog_name, file_name, include_path, out_file_name, *args):
    index = cindex.Index.create()
    translation_unit = index.parse(file_name, ['-x', 'c++', '-std=c++20', '-I', include_path, *args])

    collector = ExportedNamesCollector(include_paths_regex=f'^{include_path}')
    collector.collect_names(translation_unit)

    with open(out_file_name, 'w') as out_file:
        generate_exports_from_name_map(collector.get_collected_names(), out_file)


GLFW_ARGS = ['main.py', 'glfw-3.3.8/include/GLFW/glfw3.h', 'glfw-3.3.8/include', 'glfw.cppm',
             '-DGLFW_INCLUDE_VULKAN=1', '-DVK_VERSION_1_0=1']

ASSIMP_ARGS = ['main.py', 'assimp/include/assimp_all.h', 'assimp/include', 'assimp.cppm']

GSL_ARGS = ['main.py', 'gsl/include/gsl/gsl', 'gsl/include', 'gsl.cppm']


def create_mega_include(include_path, ext_glob, out_file_name):
    with open(f'{include_path}/{out_file_name}', 'w') as out_file:
        for included_file in glob.glob(f'**/*.{ext_glob}', root_dir=include_path, recursive=True):
            out_file.write(f'#include "{included_file.replace('\\', '/')}"\n')


if __name__ == '__main__':
    # create_mega_include('assimp/include', '*', 'assimp_all.h')
    # main(*GLFW_ARGS)
    main(*ASSIMP_ARGS)
    # main(*GSL_ARGS)
