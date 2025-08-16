import abc
import json
import pathlib
import requests

from .Auxiliary import eprint

datadir = pathlib.Path("../data/")

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

class APIDownload(Download):
    def __init__(self, endpoint, **kwargs):
        super().__init__(f"https://datatracker.ietf.org/api/{endpoint}?" + \
                "&".join([
                    f"{k}={v}" for k,v in kwargs.items() if v is not None
                    ]), **kwargs)

    def get_json(self):
        return json.loads(self.get())

class ArchiveDownload(Download):
    def __init__(self, file):
        super().__init__(f"https://www.ietf.org/archive/id/{file}")

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
            json.dump(self._meta, f)

    @property
    def islocal(self):
        return (datadir / self.filename()).exists()

class IETF(FileBacked):
    def __new__(cls, *args, **kwargs):
        try:
            return cls.instance
        except AttributeError:
            cls.instance = (ietf := super(IETF, cls).__new__(cls, *args, **kwargs))
            return ietf

    def __init__(ietf, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ietf.submissions = {}
        ietf.documents = {}

    def download(self):
        return { "last_submission_id": 1990 }

    def filename(ietf):
        return "meta.json"

    def refresh(ietf, limit: int = 1):
        loaded = []
        while limit > 0:
            # Is there any new submission?
            ietf.meta["last_submission_id"] += 1
            s = Submission(ietf.meta["last_submission_id"])
            if s.islocal:
                ietf.store()
                continue

            # TODO end if that nothing new is there
            try:
                s.meta
            except NotFoundException:
                ietf.store()
                continue

            try:
                s.document.mirror(s.rev)
            except DocumentNotFound as e:
                print(e)
                ietf.store()
                continue

            ietf.store()
            loaded.append(s.document)

            limit -= 1

        return loaded

class Submission(FileBacked):
    def __new__(cls, id: int, *args, **kwargs):
        try:
            return IETF().submissions[id]
        except KeyError:
            IETF().submissions[id] = (s := super(Submission, cls).__new__(cls, *args, **kwargs))
            return s

    def __init__(self, id: int, *args, **kwargs):
        self.id = id
        super().__init__(*args, **kwargs)

    def filename(self):
        return f"submission/{self.id}.json"

    def download(self):
        meta = APIDownload(f"v1/submit/submission/{self.id}").get_json()
        if meta["id"] != self.id:
            eprint(meta)
            raise AssertionError(f"Received a garbled submission record for ID {self.id}")

        return meta

    @property
    def name(self):
        return self.meta["name"]

    @property
    def rev(self):
        return self.meta["rev"]

    @property
    def document(self):
        return Document(self.name)

class DocumentNotFound(Exception):
    def __init__(self, document):
        super().__init__(f"Document {document.name} does not exist")
        self.document = document

class Document(FileBacked):
    def __init__(self, name: str, *args, **kwargs):
        self.name = name
        super().__init__(*args, **kwargs)

    def filename(self):
        return f"document/{self.name}.json"

    def download(self):
        try:
            meta = APIDownload(f"v1/doc/document/{self.name}").get_json()
        except NotFoundException as e:
            raise DocumentNotFound(self) from e

        if meta["name"] != self.name:
            eprint(meta)
            raise AssertionError(f"Received a garbled document record for {self.name}")

        # Create explicit revision list
        meta["_revisions"] = { f"{i:02d}": {} for i in range(int(meta["rev"])+1) }
        for slink in meta["submissions"]:
            s = Submission(int(slink.split("/api/v1/submit/submission/")[1].split("/")[0]))
            try:
                old_id = meta["_revisions"][s.rev]["submission"]
                try:
                    meta["_revisions"][s.rev]["overridden_submissions"].append(old_id)
                except KeyError:
                    meta["_revisions"][s.rev]["overridden_submissions"] = [ old_id ]
            except KeyError:
                pass

            meta["_revisions"][s.rev]["submission"] = s.id

        return meta

    @property
    def last_rev(self):
        return self.meta["rev"]

    def mirror(self, upto: str):
        revs = self.meta["_revisions"]
        if upto not in revs:
            nm = self.download()
            for rev, info in nm["_revisions"].items():
                if rev not in revs:
                    revs[rev] = info

        for rev, info in revs.items():
            try:
                fts = info["file_types"]
            except KeyError:
                try:
                    s = Submission(info["submission"])
                    ftl = s.meta["file_types"].split(",")
                    fts = {}
                    for k in ftl:
                        assert(k[0] == ".")
                        fts[k[1:]] = None
                except KeyError:
                    fts = { "xml": None, "txt": None }

            for ft in fts:
                fn = f"{self.name}-{rev}.{ft}"
                if (fp := (datadir / "document" / fn)).exists():
                    fts[ft] = True
                    eprint(f"I: Found {fn}")
                else:
                    if fts[ft] == False:
                        continue
                    if fts[ft] == True:
                        eprint(f"W: Re-downloading {fn}!")
                    try:
                        contents = ArchiveDownload(fn).get()
                    except NotFoundException as de:
                        fts[ft] = False
                        continue

                    with open(fp, "w") as f:
                        f.write(contents)

                    fts[ft] = True

            info["file_types"] = fts

        self.store()

def refresh(*args, **kwargs):
    return IETF().refresh()
