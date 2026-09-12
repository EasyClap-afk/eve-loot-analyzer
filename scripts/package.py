"""Package the Windows folder using read-only access to application files."""
import sys
import time
import zipfile
from pathlib import Path

root=Path(sys.argv[1])
target=root/'EveLootAnalyzer-Windows.zip'
temporary=target.with_suffix('.zip.tmp')
files=sorted(p for p in (root/'EveLootAnalyzer').rglob('*') if p.is_file())
for attempt in range(10):
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in files:archive.write(path,path.relative_to(root))
        temporary.replace(target)
        break
    except PermissionError:
        if attempt==9:raise
        time.sleep(1)
print(target)
