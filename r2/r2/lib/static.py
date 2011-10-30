#!/usr/bin/env python
import sys
import os
import hashlib
import json
import base64
import shutil

def generate_static_name(name, base=None, shorthash=None):
    """Generate a unique filename.
    
    Unique filenames are generated by base 64 encoding the first 64 bits of
    the SHA1 hash. This hash string is added to the filename before the extension.
    """
    if base: path = os.path.join(base, name)
    sha = hashlib.sha1(open(path).read()).digest()
    shorthash = base64.urlsafe_b64encode(sha[0:8]).rstrip("=")
    name, ext = os.path.splitext(name)
    return name + '.' + shorthash + ext

def update_static_names(names_file, files):
    """Generate a unique file name mapping for ``files`` and write it to a
    JSON file at ``names_file``."""
    if os.path.exists(names_file):
        names = json.load(open(names_file))
    else:
        names = {}

    base = os.path.dirname(names_file)
    for path in files:
        name = os.path.relpath(path, base)
        mangled_name = generate_static_name(name, base)
        names[name] = mangled_name

        if not os.path.islink(path):
            mangled_path = os.path.join(base, mangled_name)
            shutil.move(path, mangled_path)
            os.symlink(mangled_name, path)

    json_enc = json.JSONEncoder(indent=2, sort_keys=True)
    open(names_file, "w").write(json_enc.encode(names))

    return names

if __name__ == "__main__":
    update_static_names(sys.argv[1], sys.argv[2:])
