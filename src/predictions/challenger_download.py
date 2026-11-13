"""Run-local verified object reuse; every archive's server index and manifest stay independently authenticated."""

import gzip
import hashlib
import io
import os
import re
from collections import Counter
from pathlib import Path

from src.rankings.archive_storage import BUCKET, MAX_RAW_BYTES, references


class CachedArchiveClient:
    def __init__(self, client, directory: Path, *, dry_run=True):
        self.client, self.directory = client, directory.resolve()
        self.objects = self.directory / "verified-objects"
        self.dry_run = dry_run
        if not dry_run:
            self.objects.mkdir(exist_ok=False)
        self.storage = self
        self.counts = Counter()

    def table(self, name):
        return self.client.table(name)

    def from_(self, bucket):
        if bucket != BUCKET:
            raise ValueError("Object reuse is restricted to the private input archive bucket")
        return self

    @staticmethod
    def verified(compressed, sha):
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
            raw = handle.read(MAX_RAW_BYTES + 1)
        if len(raw) > MAX_RAW_BYTES or hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("Cached archive object failed content verification")

    def download(self, name):
        if self.dry_run:
            return self.client.storage.from_(BUCKET).download(name)
        match = re.fullmatch(r"objects/([a-f0-9]{64})\.gz", name)
        if match is None:
            # Manifests are always fetched from the server, never reused from this cache.
            return self.client.storage.from_(BUCKET).download(name)
        target = self.objects / (match[1] + ".gz")
        if target.exists():
            compressed = target.read_bytes()
            self.verified(compressed, match[1])
            self.counts["objects_reused"] += 1
        else:
            compressed = self.client.storage.from_(BUCKET).download(name)
            self.verified(compressed, match[1])
            with target.open("xb") as handle:
                handle.write(compressed)
            self.counts["objects_downloaded"] += 1
        return compressed

    def share_local_objects(self, archive):
        if self.dry_run:
            return
        directory = archive.directory.resolve()
        if not directory.is_relative_to(self.directory) or directory == self.directory:
            raise ValueError("Only newly downloaded owned archives can share cached objects")
        for name in sorted({reference["object"] for reference in references(archive.manifest)}):
            match = re.fullmatch(r"objects/([a-f0-9]{64})\.gz", name)
            if match is None:
                raise ValueError("Invalid archive object path")
            original = self.objects / (match[1] + ".gz")
            target = directory / name
            if target.samefile(original):
                continue
            temporary = target.with_suffix(".link")
            try:
                os.link(original, temporary)
                os.replace(temporary, target)
                self.counts["local_files_shared"] += 1
            except OSError:
                # Unsupported hard links leave the already verified independent copy intact.
                temporary.unlink(missing_ok=True)
