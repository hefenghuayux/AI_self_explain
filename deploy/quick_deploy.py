import argparse
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SOURCE_PATHS = (
    ".dockerignore",
    "Dockerfile",
    "backend/app",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/alembic",
    "backend/alembic.ini",
    "frontend",
    "scripts/deepseek_v4_tokenizer",
)
REQUIRED_FILES = (
    "Dockerfile",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/alembic.ini",
    "frontend/Dockerfile",
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
    "frontend/nginx.conf",
    "frontend/index.html",
    "scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer.json",
    "scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer_config.json",
)


def source_files(root, commit=None):
    if commit is not None:
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Commit must be a full lowercase 40-character SHA")
        resolved = (
            subprocess.check_output(
                ["git", "rev-parse", "--verify", commit + "^{commit}"], cwd=root
            )
            .decode()
            .strip()
        )
        if resolved != commit:
            raise ValueError("Deployment source must identify an exact commit")
        entries = subprocess.check_output(
            ["git", "ls-tree", "-rz", commit, "--", *SOURCE_PATHS], cwd=root
        )
        modes = {}
        for entry in entries.split(b"\0"):
            if entry:
                metadata, name = entry.split(b"\t", 1)
                modes[os.fsdecode(name)] = metadata.split()[0]
        names = modes
    else:
        modes = {}
        raw = subprocess.check_output(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *SOURCE_PATHS,
            ],
            cwd=root,
        )
        names = {os.fsdecode(item) for item in raw.split(b"\0") if item}
    selected = []
    for name in sorted(names):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Invalid source path: " + name)
        if any(
            part.startswith(".env")
            or part
            in {
                "node_modules",
                "dist",
                "__pycache__",
                ".venv",
                ".git",
                "private",
                ".pytest_cache",
                ".ruff_cache",
            }
            for part in relative.parts
        ):
            continue
        if relative.suffix.lower() in {".pem", ".key", ".pfx", ".p12", ".log", ".pyc"}:
            continue
        if commit is not None:
            if modes[name] not in {b"100644", b"100755"}:
                raise RuntimeError("Commit source is not a regular file: " + name)
            selected.append(name)
            continue
        filename = root / name
        if filename.is_symlink() or any(
            parent.is_symlink() for parent in filename.parents if parent != root
        ):
            raise RuntimeError("Source symlinks are unsupported: " + name)
        if filename.exists():
            if not filename.is_file():
                raise RuntimeError("Source is not a regular file: " + name)
            selected.append(name)
    missing = set(REQUIRED_FILES) - set(selected)
    if missing:
        raise RuntimeError("Missing deployment sources: " + ", ".join(sorted(missing)))
    return selected


def prepare(root, directory, commit=None):
    files = source_files(root, commit)
    directory.mkdir(parents=True, exist_ok=False)
    archive = directory / "source.tar.gz"
    with ExitStack() as stack:
        snapshot = None
        if commit is not None:
            source = subprocess.check_output(
                [
                    "git",
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "core.eol=lf",
                    "archive",
                    "--format=tar",
                    commit,
                    "--",
                    *files,
                ],
                cwd=root,
            )
            snapshot = stack.enter_context(tarfile.open(fileobj=io.BytesIO(source)))
        package = stack.enter_context(tarfile.open(archive, "w:gz"))
        for name in files:
            filename = root / name
            if snapshot is not None:
                info = snapshot.getmember(name)
                source = snapshot.extractfile(name)
            else:
                info = package.gettarinfo(str(filename), arcname=name)
                source = filename.open("rb")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with source:
                package.addfile(info, source)
        dockerfile = (
            snapshot.extractfile("Dockerfile").read().decode("utf-8")
            if snapshot is not None
            else (root / "Dockerfile").read_text(encoding="utf-8")
        )
        original = "RUN uv sync --project backend --frozen --no-dev"
        replacement = (
            "RUN python -c \"from pathlib import Path; filename=Path('backend/uv.lock'); "
            "content=filename.read_text(); content=content.replace('https://pypi.org/simple', "
            "'https://mirrors.aliyun.com/pypi/simple/').replace('https://files.pythonhosted.org/packages/', "
            "'https://mirrors.aliyun.com/pypi/packages/'); filename.write_text(content)\" \\\n"
            "    && uv sync --project backend --frozen --no-dev --index-url https://mirrors.aliyun.com/pypi/simple/"
        )
        if dockerfile.count(original) != 1:
            raise RuntimeError(
                "Backend Dockerfile changed; review the mirror transformation before deploying."
            )
        payload = dockerfile.replace(original, replacement).encode("utf-8")
        info = tarfile.TarInfo("Dockerfile.quick")
        info.size = len(payload)
        info.mode = 0o644
        package.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    source_commit = (
        commit
        or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
    )
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--", *SOURCE_PATHS], cwd=root, text=True
    )
    manifest = {
        "commit": source_commit,
        "source_mode": "commit" if commit is not None else "working_tree",
        "working_tree_changes": commit is None and bool(status.strip()),
        "source_sha256": digest,
        "files": files,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Deploy the current local source tree to the existing ECS."
    )
    parser.add_argument("--server", default="182.92.219.177")
    parser.add_argument("--user", default="devuser")
    parser.add_argument("--key", type=Path, default=Path.home() / ".ssh/id_rsa_aliyun")
    parser.add_argument(
        "--known-hosts", type=Path, help="Use only this trusted SSH host-key file"
    )
    parser.add_argument(
        "--commit", help="Package only this full commit SHA, excluding local edits"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--prepare-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.commit is not None and not re.fullmatch(
        r"[0-9a-f]{40}", arguments.commit
    ):
        parser.error("--commit must be a full lowercase 40-character SHA")
    for value in [arguments.server, arguments.user]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            parser.error("Server and user must be plain host/user names.")
    root = Path(__file__).resolve().parents[1]
    helper = Path(__file__).with_name("quick_deploy_server.py")
    ssh = [
        "ssh",
        "-i",
        str(arguments.key),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=12",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if arguments.known_hosts is not None:
        if not arguments.known_hosts.is_file():
            parser.error("SSH known_hosts file does not exist")
        ssh += [
            "-o",
            "UserKnownHostsFile=" + str(arguments.known_hosts),
            "-o",
            "GlobalKnownHostsFile=/dev/null",
        ]
    ssh.append(arguments.user + "@" + arguments.server)
    if not arguments.prepare_only:
        if not arguments.key.is_file():
            parser.error("SSH key does not exist: " + str(arguments.key))
        subprocess.run(
            ssh + ["python3 - --check"], input=helper.read_bytes(), check=True
        )
    if arguments.check:
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    directory = Path(__file__).parent / "private" / ("quick-" + timestamp)
    if os.name == "nt":
        directory.parent.mkdir(parents=True, exist_ok=True)
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(
            [
                "icacls",
                str(directory.parent),
                "/inheritance:r",
                "/grant:r",
                account + ":(OI)(CI)F",
                "SYSTEM:(OI)(CI)F",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    manifest = prepare(root, directory, arguments.commit)
    release = "local-" + timestamp + "-" + manifest["source_sha256"][:12]
    print(
        "Prepared {} files, {:.2f} MiB, local changes={}".format(
            len(manifest["files"]),
            (directory / "source.tar.gz").stat().st_size / 1048576,
            manifest["working_tree_changes"],
        ),
        flush=True,
    )
    print("Artifacts: " + str(directory), flush=True)
    if arguments.prepare_only:
        return
    remote = "/srv/ai-self-explain/staging/" + release
    subprocess.run(ssh + ["umask 077 && mkdir " + shlex.quote(remote)], check=True)
    for filename in ["source.tar.gz", "manifest.json"]:
        with (directory / filename).open("rb") as source:
            subprocess.run(
                ssh + ["cat > " + shlex.quote(remote + "/" + filename)],
                stdin=source,
                check=True,
            )
    shutil.copyfile(helper, directory / helper.name)
    subprocess.run(
        ssh + ["python3 - --release " + shlex.quote(release)],
        input=helper.read_bytes(),
        check=True,
    )
    print("DEPLOYMENT_SUCCEEDED " + release, flush=True)


if __name__ == "__main__":
    main()
