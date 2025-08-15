import IETF
import os
import subprocess

try:
    loaded = IETF.refresh(limit=1)

except IETF.DownloadException as e:
    print(f"Failed to download from {e.request.url}: {e.request.status_code}")
    print(e.request)
    exit(1)

if len(loaded) == 0:
    exit(0)

assert(len(loaded) == 1)

os.chdir(IETF.datadir)
subprocess.run(["git", "add", "document/*", "submission/*", "meta.json"])
subprocess.run(["git", "commit", "-m", f"Auto: {loaded[0].name}"])
