import IETF
import os
import random
import subprocess
import time

begin = True
while True:
    if begin:
        begin = False
    else:
        s = random.randrange(2, 10)
        print(f"Sleeping for {s} s")
        time.sleep(s)

    try:
        print("Loading …")
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
    subprocess.run(["git", "commit", "--quiet", "-m", f"Auto: {loaded[0].name}"])
    subprocess.run(["git", "show", "-s", "--shortstat"])
