#!/usr/bin/env python3
"""Fix syntax issues in generated test stubs"""
import os

# Test stub files to fix
stub_files = [
    'tests/test_extractors__init__py.py',
    'tests/test_extractors_python_py.py',
    'tests/test_extractors_javascript_py.py',
    'tests/test_extractors_api_routes_py.py',
    'tests/test_extraction_types_py.py',
    'tests/test_subsystem_extractor_py.py'
]

def fix_stub_file(filepath):
    """Fix import syntax in a stub file"""
    if not os.path.exists(filepath):
        return

    with open(filepath, 'r') as f:
        content = f.read()

    # Fix the wildcard import issue
    content = content.replace('from codegraph.', 'import codegraph.')
    content = content.replace(' import *\n', '\n')
    content = content.replace(' import *\"', '\"')

    with open(filepath, 'w') as f:
        f.write(content)

    print(f"Fixed: {filepath}")

def main():
    print("Fixing test stub syntax issues...")
    for stub in stub_files:
        fix_stub_file(stub)
    print("All stubs fixed!")

if __name__ == '__main__':
    main()