"""Preserve a complete evaluation's reports and per-question audit in home storage."""
import hashlib
import json
import shutil
import tarfile
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def preserve(root, destination, source=None):
    root, destination = Path(root), Path(destination)
    result = json.loads((root / "full-results.json").read_text())
    expected = {d["query_id"] for d in result["details"]}
    if len(expected) != result["queries"]:
        raise RuntimeError("Incomplete/duplicate score report")
    destination.mkdir(parents=True, exist_ok=True)
    files = list(root.glob("*.json"))
    for f in files:
        target = destination / f.name
        shutil.copy2(f, target)
        if digest(f) != digest(target):
            raise RuntimeError("Archive copy mismatch: " + str(f))
    for name in ("trajectories", "judgments"):
        paths = [root / name / (qid + ".json") for qid in sorted(expected)]
        for p in paths:
            record = json.loads(p.read_text())
            if record.get("status") == "infrastructure_error" or record["query_id"] != p.stem:
                raise RuntimeError("Invalid audit file: " + str(p))
        target = destination / (name + ".tar.gz")
        temporary = target.with_suffix(".partial")
        with tarfile.open(temporary, "w:gz") as archive:
            for p in paths:
                archive.add(p, arcname=name + "/" + p.name)
        with tarfile.open(temporary, "r:gz") as archive:
            for member in archive:
                if member.isfile():
                    stored = archive.extractfile(member).read()
                    if hashlib.sha256(stored).hexdigest() != digest(root / member.name):
                        raise RuntimeError("Compressed audit mismatch: " + member.name)
        temporary.replace(target)
    if source:
        with tarfile.open(destination / "source.tar.gz", "w:gz") as archive:
            archive.add(source, arcname="source", filter=lambda m: None if "__pycache__" in m.name else m)
    files = sorted(p for p in destination.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (destination / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in files))
    print("Preserved complete evaluation:", destination, flush=True)
