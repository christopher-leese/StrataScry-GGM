# SPDX-License-Identifier: Apache-2.0
"""Versioned local projects. Validate before replacement; atomic same-directory save."""
import json
import os
from pathlib import Path
import tempfile
from .model import Document

MAX_FILE_BYTES = 64 * 1024**2


def no_duplicates(pairs):
    result={}
    for k,v in pairs:
        if k in result: raise ValueError('Duplicate JSON key: '+k)
        result[k]=v
    return result


def load(path):
    path=Path(path)
    if path.stat().st_size>MAX_FILE_BYTES: raise ValueError('Project exceeds the 64 MiB file limit')
    with path.open(encoding='utf-8') as f:
        data=json.load(f, object_pairs_hook=no_duplicates,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite number: '+value)))
    try: return Document.from_dict(data)
    except (KeyError,TypeError,OverflowError,AttributeError,RecursionError) as e:
        raise ValueError('Invalid project structure: '+str(e)) from e


def save(document,path):
    path=Path(path).expanduser()
    encoded=json.dumps(document.to_dict(),ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
    if len(encoded)>MAX_FILE_BYTES: raise ValueError('Project exceeds the 64 MiB file limit')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent,delete=False) as f:
            temporary=Path(f.name)
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary,path)
        document.mark_saved()
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()
