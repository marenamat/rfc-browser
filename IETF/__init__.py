import pathlib
import time

from .Auxiliary import \
        eprint, \
        FileBacked, \
        APIDownload, \
        ArchiveDownload, \
        RFCDownload, \
        NotFoundException, \
        DownloadException

from .Config import datadir

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
        return {
                "last_submission_id": 1990,
                "rfc_total_count": 0,
                "rfc_next_check": 0,
                "rfc_newest_time": "1940-01-01T01:01:01Z",
                "rfc_missing": [],
                }

    def filename(ietf):
        return "meta.json"

    def refresh(ietf, limit: int = 1):
        loaded = []
        while limit > 0:
            # Is there any RFC pending download?
            pending = ietf.meta["rfc_missing"]
            if len(pending) == 0:
                break

            rfc = RFC(pending[0])
            try:
                rfc.mirror()
            except DocumentNotFoundException as e:
                print(e)

            ietf.meta["rfc_missing"] = pending[1:]

            if rfc.meta["time"] > ietf.meta["rfc_newest_time"]:
                ietf.meta["rfc_newest_time"] = rfc.meta["time"]

            ietf.store()
            loaded.append(rfc)
            limit -= 1

        if len(loaded):
            return loaded

        if time.time() > ietf.meta["rfc_next_check"]:
            # Is there any new RFC we don't know about?
            assert(len(ietf.meta["rfc_missing"]) == 0)
            newest = ietf.meta["rfc_newest_time"]
            pending = []

            offset = 0
            while offset is not None:
                next_rfc = APIDownload(
                        "v1/doc/document/",
                        type="rfc",
                        time__gte=newest,
                        limit=100,
                        offset=offset,
                        ).get_json()

                for obj in next_rfc["objects"]:
                    rfc = RFC(obj["name"])
                    if rfc.islocal:
                        continue

                    rfc._meta = obj
                    rfc.store()

                    pending.append(rfc.name)

                if next_rfc["meta"]["next"] is None:
                    break

                offset += 100

            print(f"New {len(pending)} pending RFCs to load")
            if len(pending):
                ietf.meta["rfc_missing"] = pending
                ietf.store()
                return ietf.refresh(limit)
            else:
                ietf.meta["rfc_next_check"] = time.time() + 10800 # 3 hrs

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
            except DocumentNotFoundException as e:
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

class DocumentNotFoundException(Exception):
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
            raise DocumentNotFoundException(self) from e

        if meta["name"] != self.name:
            eprint(meta)
            raise AssertionError(f"Received a garbled document record for {self.name}")

        # Create explicit revision list
        if meta["rev"] == "":
            meta["_revisions"] = {}
        else:
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
        try:
            revs = self.meta["_revisions"]
        except KeyError:
            eprint(f"W: No revisions of document {self.name}")
            revs = {}

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

class RFC(Document):
    def __init__(self, name: str, *args, **kwargs):
        assert(name.startswith("rfc"))
        super().__init__(*args, name, **kwargs)

    def mirror(self):
        fts = { k: None for k in ("xml", "html", "txt", "pdf") }
        suc = 0
        for fmt in (*(list(fts)), "pdf"):
            fp = datadir / "document" / f'{self.name}.{fmt}'
            if fp.exists():
                fts[fmt] = True
                continue

            if fmt == "pdf" and suc > 0:
                continue

            try:
                contents = RFCDownload(self.name[3:], fmt).get_binary()
            except NotFoundException:
                fts[fmt] = False
                continue

            with open(fp, "wb") as f:
                f.write(contents)

            fts[fmt] = True

        self.meta["file_types"] = fts
        self.store()


def refresh(*args, **kwargs):
    return IETF().refresh()

__all__ = [ refresh, datadir, DownloadException ]
