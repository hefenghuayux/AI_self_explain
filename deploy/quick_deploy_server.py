import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.request


ROOT = Path("/srv/ai-self-explain")
OUTPUT_BROKEN = False
LOG_PATH = None
SCHEMA_CHECK = """
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from app.core.config import Settings
engine = None
try:
    settings = Settings()
    expected = set(ScriptDirectory.from_config(Config('/app/backend/alembic.ini')).get_heads())
    engine = create_engine(settings.database_url, connect_args={'connect_timeout': 5})
    with engine.connect() as connection:
        actual = set(MigrationContext.configure(connection).get_current_heads())
except Exception as error:
    raise SystemExit('Database schema check failed: ' + type(error).__name__) from None
finally:
    if engine is not None:
        engine.dispose()
if actual != expected:
    raise SystemExit('Schema mismatch: actual=' + str(sorted(actual)) + ', code=' + str(sorted(expected)) + '; migration requires separate authorization')
print('SCHEMA_MATCH ' + ','.join(sorted(actual)))
"""


def log(message):
    global OUTPUT_BROKEN
    if LOG_PATH is not None:
        try:
            with LOG_PATH.open("a") as output:
                output.write(message + "\n")
        except OSError:
            pass
    if not OUTPUT_BROKEN:
        try:
            print(message, flush=True)
        except BrokenPipeError:
            OUTPUT_BROKEN = True


def run(command, **arguments):
    log("RUN " + " ".join(command[:4]))
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        errors="replace",
        **arguments,
    ) as process:
        try:
            for line in process.stdout:
                log(line.rstrip("\r\n"))
            result = process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if result != 0:
        raise subprocess.CalledProcessError(result, command)


def inspect_service(name):
    output = subprocess.check_output(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .}}",
            "ai-self-explain-" + name + "-1",
        ]
    ).decode()
    container = json.loads(output)
    if (
        container["Config"]["Labels"].get("com.docker.compose.project")
        != "ai-self-explain"
    ):
        raise RuntimeError("Unexpected Compose project for " + name)
    return {
        "reference": container["Config"]["Image"],
        "id": container["Image"],
        "running": container["State"]["Running"],
    }


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:18081/api/health", timeout=5) as response:
        if json.load(response) != {"status": "ok", "database": "ok"}:
            raise RuntimeError("Unexpected application health response")
    with opener.open("http://127.0.0.1:18081/login", timeout=5) as response:
        if b"/assets/" not in response.read():
            raise RuntimeError("Frontend production assets missing")


def preflight():
    current = ROOT / "current"
    release = current.resolve()
    if not current.is_symlink() or release.parent != ROOT / "releases":
        raise RuntimeError("current must point directly into releases")
    for filename in ["compose.server.yml", "Caddyfile.server", ".env.production"]:
        if not (release / filename).is_file():
            raise RuntimeError("Missing server deployment file: " + filename)
    if (release / ".env.production").resolve() != ROOT / "shared/.env.production":
        raise RuntimeError("Release must use shared/.env.production")
    images = {
        name: inspect_service(name)
        for name in ["backend", "frontend", "mysql", "caddy"]
    }
    if not all(item["running"] for item in images.values()):
        raise RuntimeError("An application service is not running")
    if shutil.disk_usage(str(ROOT)).free < 3 * 1024**3:
        raise RuntimeError("Need at least 3 GiB free disk space before building")
    run(["docker", "compose", "version"])
    health()
    log(json.dumps({"current": str(release), "images": images}))
    return release, images


def extract_sources(archive, destination):
    with tarfile.open(str(archive), "r:gz") as package:
        members = package.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise RuntimeError("Unsafe archive member: " + member.name)
            allowed = path.parts[0] in {
                "backend",
                "frontend",
                "scripts",
            } or member.name in {
                "Dockerfile",
                "Dockerfile.quick",
                ".dockerignore",
            }
            if not allowed:
                raise RuntimeError("Unexpected archive member: " + member.name)
            if any(part.startswith(".env") for part in path.parts):
                raise RuntimeError("Environment files must never be uploaded")
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(str(target), member.mode & 0o755)


def compose(release, overrides, arguments, capture=False):
    command = [
        "docker",
        "compose",
        "-p",
        "ai-self-explain",
        "--env-file",
        str(ROOT / "shared/.env.production"),
        "-f",
        str(release / "compose.server.yml"),
        "-f",
        str(overrides),
    ] + arguments
    if capture:
        return subprocess.check_output(
            command, cwd=str(release), stdin=subprocess.DEVNULL
        )
    run(command, cwd=str(release), stdin=subprocess.DEVNULL)


def write_overrides(path, images):
    path.write_text(
        json.dumps(
            {
                "services": {
                    name: {"image": reference} for name, reference in images.items()
                }
            },
            indent=2,
        )
    )


def verify_images(images):
    for name, expected in images.items():
        actual = inspect_service(name)
        expected_id = (
            subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    expected,
                ]
            )
            .decode()
            .strip()
        )
        if not actual["running"] or actual["id"] != expected_id:
            raise RuntimeError("Unexpected running image for " + name)


def wait_healthy(images):
    deadline = time.monotonic() + 120
    last_error = None
    while time.monotonic() < deadline:
        try:
            verify_images(images)
            health()
            return
        except Exception as error:
            last_error = type(error).__name__
            time.sleep(2)
    raise RuntimeError("Release health timeout: " + str(last_error))


def deploy(release_name):
    import fcntl

    global LOG_PATH
    if not re.match(r"^local-\d{8}-\d{6}-\d{6}-[0-9a-f]{12}$", release_name):
        raise RuntimeError("Invalid release identifier")
    with (ROOT / "shared/.deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous, old_images = preflight()
        staging = ROOT / "staging" / release_name
        LOG_PATH = staging / "deployment.log"
        manifest = json.loads((staging / "manifest.json").read_text())
        archive = staging / "source.tar.gz"
        with archive.open("rb") as source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != manifest["source_sha256"]:
            raise RuntimeError("Uploaded source checksum mismatch")
        release = ROOT / "releases" / release_name
        release.mkdir(mode=0o700)
        extract_sources(archive, release)
        for filename in [
            "compose.server.yml",
            "Caddyfile.server",
            "compose.tunnel.yml",
            "Dockerfile.tunnel",
            "configure_tunnel.sh",
        ]:
            if (previous / filename).is_file():
                shutil.copyfile(str(previous / filename), str(release / filename))
        (release / ".env.production").symlink_to(ROOT / "shared/.env.production")
        shutil.copyfile(
            str(staging / "manifest.json"), str(release / "source-manifest.json")
        )
        images = {
            name: "ai-self-explain-" + name + ":" + release_name
            for name in ["backend", "frontend"]
        }
        overrides = release / "compose.images.json"
        write_overrides(overrides, images)
        rollback_overrides = staging / "rollback.images.json"
        write_overrides(
            rollback_overrides,
            {name: old_images[name]["id"] for name in ["backend", "frontend"]},
        )
        build_env = os.environ.copy()
        build_env["DOCKER_BUILDKIT"] = "0"
        for name, dockerfile in [
            ("backend", "Dockerfile.quick"),
            ("frontend", "frontend/Dockerfile"),
        ]:
            run(
                [
                    "docker",
                    "build",
                    "--pull=false",
                    "-f",
                    dockerfile,
                    "-t",
                    images[name],
                    ".",
                ],
                cwd=str(release),
                env=build_env,
                stdin=subprocess.DEVNULL,
            )
        compose(release, overrides, ["config", "--quiet"])
        resolved = json.loads(
            compose(
                release, overrides, ["config", "--format", "json"], capture=True
            ).decode()
        )
        if any(
            resolved["services"][name]["image"] != reference
            for name, reference in images.items()
        ):
            raise RuntimeError("Resolved Compose images do not match the new release")
        compose(
            release,
            overrides,
            ["run", "--rm", "--no-deps", "-T", "backend", "python", "-c", SCHEMA_CHECK],
        )
        record = {
            "release": release_name,
            "previous": str(previous),
            "images": images,
            "previous_images": old_images,
            "source": manifest,
            "status": "prepared",
        }
        (release / "deployment.json").write_text(json.dumps(record, indent=2))
        started = False
        try:
            started = True
            compose(
                release,
                overrides,
                [
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "backend",
                    "frontend",
                ],
            )
            wait_healthy(images)
            if (ROOT / "current").resolve() != previous:
                raise RuntimeError("current changed during deployment")
            record["status"] = "validated"
            (release / "deployment.json").write_text(json.dumps(record, indent=2))
            temporary = ROOT / (".current-" + release_name)
            temporary.symlink_to(release)
            os.replace(str(temporary), str(ROOT / "current"))
            record["status"] = "healthy"
            (release / "deployment.json").write_text(json.dumps(record, indent=2))
            log("RELEASE_HEALTHY " + release_name)
        except BaseException as original_error:
            if started:
                log("DEPLOY_FAILED restoring previous backend/frontend images")
                try:
                    compose(
                        previous,
                        rollback_overrides,
                        [
                            "up",
                            "-d",
                            "--no-deps",
                            "--no-build",
                            "--pull",
                            "never",
                            "--wait",
                            "--wait-timeout",
                            "120",
                            "backend",
                            "frontend",
                        ],
                    )
                    wait_healthy(
                        {
                            name: old_images[name]["id"]
                            for name in ["backend", "frontend"]
                        }
                    )
                    if (ROOT / "current").resolve() == release:
                        temporary = ROOT / (".rollback-" + release_name)
                        temporary.symlink_to(previous)
                        os.replace(str(temporary), str(ROOT / "current"))
                    record["status"] = "rolled_back"
                    (release / "deployment.json").write_text(
                        json.dumps(record, indent=2)
                    )
                    log("ROLLBACK_HEALTHY " + str(previous))
                except BaseException as rollback_error:
                    raise RuntimeError(
                        "Deployment failed ({!r}); rollback also failed ({!r}); inspect {}".format(
                            original_error, rollback_error, staging
                        )
                    ) from original_error
            raise


def interrupted(signum, frame):
    raise RuntimeError("Deployment interrupted by signal " + str(signum))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--release")
    arguments = parser.parse_args()
    for name in ["SIGHUP", "SIGTERM", "SIGINT"]:
        signal.signal(getattr(signal, name), interrupted)
    if arguments.check:
        preflight()
    else:
        deploy(arguments.release)


if __name__ == "__main__":
    main()
