"""Canonical protection shared by legacy file serving and ingestion consumers."""
import os
from pathlib import Path


class ProtectedLibraryPath(ValueError):
    pass


def protected_roots():
    data = Path.home()/'Documents/SACC_Data'
    database = Path(os.getenv('SACC_LIBRARY_DB',str(data/'library/staging/sacc-library.sqlite3'))).expanduser()
    return [p.resolve() for p in [data/'recovery',data/'library',data/'backups',data/'calibration',data/'repair_validation',database.parent,
            *(Path(p).expanduser() for p in os.getenv('SACC_LIBRARY_PROTECTED_ROOTS','').split(os.pathsep) if p)]]


def unprotected_path(value, *, ancestors=True):
    path = Path(value).expanduser().resolve()
    if any(path == root or path.is_relative_to(root) or (ancestors and root.is_relative_to(path))
           for root in protected_roots()):
        raise ProtectedLibraryPath('Use the protected Library API for recovery data')
    return path
