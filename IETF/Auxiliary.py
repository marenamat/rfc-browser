import abc
import json
import requests
import sys

from .Config import datadir

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

class DownloadException(Exception):
    def __new__(cls, *args, request, **kwargs):
        if request.status_code == 404 and cls is not NotFoundException:
            return NotFoundException(*args, request=request, **kwargs)
        else:
            return super(DownloadException, cls).__new__(cls, *args, **kwargs)

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request

class NotFoundException(DownloadException):
    pass

class Download:
    def __init__(self, uri):
        self.uri = uri

    def get(self):
        r = requests.get(self.uri, headers={
            "user-agent": "marenamat-ietf-mirror/0.0.1",
            })
        if r.ok:
            return r.text
        else:
            raise DownloadException(request=r)

    def get_binary(self):
        r = requests.get(self.uri, headers={
            "user-agent": "marenamat-ietf-mirror/0.0.1",
            })
        if r.ok:
            return r.content
        else:
            raise DownloadException(request=r)

class APIDownload(Download):
    def __init__(self, endpoint, **kwargs):
        super().__init__(f"https://datatracker.ietf.org/api/{endpoint}?" + \
                "&".join([
                    f"{k}={v}" for k,v in kwargs.items() if v is not None
                    ]))

    def get_json(self):
        return json.loads(self.get())

class ArchiveDownload(Download):
    def __init__(self, file):
        super().__init__(f"https://www.ietf.org/archive/id/{file}")

class RFCDownload(Download):
    def __init__(self, num, fmt):
        super().__init__(f"https://www.rfc-editor.org/rfc/rfc{num}.{fmt}")

class FileBacked(abc.ABC):
    @abc.abstractmethod
    def filename(self):
        pass

    @property
    def meta(self):
        try:
            return self._meta
        except AttributeError:
            pass

        try:
            with open(datadir / self.filename(), "r") as f:
                self._meta = json.load(f)
        except FileNotFoundError:
            self._meta = self.download()
            self.store()

        return self._meta

    @meta.setter
    def meta(self, value):
        self._meta = value
        self.store()

    def store(self):
        with open(datadir / self.filename(), "w") as f:
            json.dump(self._meta, f, indent=2)

    @property
    def islocal(self):
        return (datadir / self.filename()).exists()
