# Running on Rocky Linux 9

The [README](../README.md) setup path targets Ubuntu, on WSL or bare metal. This
page covers only what differs on Rocky Linux 9. Everything after the environment
is created is identical: the same `uv` commands, the same entry points, the same
cache layout.

Verified on Rocky Linux 9.8 (Blue Onyx), glibc 2.34, Python 3.13, uv 0.12.3.

## Install the prerequisites

Rocky ships every package this project needs in AppStream, so no EPEL repository
is required.

```bash
sudo dnf install -y git git-lfs mesa-libGL libX11
git lfs install
```

Substitutions from the README's Ubuntu instructions:

| Ubuntu (`apt`) | Rocky 9 (`dnf`) |
| --- | --- |
| `git git-lfs` | `git git-lfs` |
| `libgl1` | `mesa-libGL` |
| `libx11-6` | `libX11` |
| `pipx` | needs EPEL; see below |

`pipx` is not in AppStream. Either enable EPEL with
`sudo dnf install -y epel-release` and follow the README, or install `uv` from
its standalone binary. `uv` manages its own Python, so the system `python3`
version does not matter.

## Native libraries for the CAD kernel

`mesa-libGL` and `libX11` are not optional, and they are not about rendering. The
`OCP` OpenCascade bindings link against them at import time, so a machine without
them fails before any geometry is read:

```text
ImportError: libGL.so.1: cannot open shared object file: No such file or directory
```

The failure surfaces as a pytest collection error in three test modules rather
than as a clear missing-dependency message. `pytest.importorskip("OCP")` does not
absorb it, because recent pytest only auto-skips on `ModuleNotFoundError` and
this is a plain `ImportError`.

To list what is still missing on a given machine:

```bash
ldd .venv/lib/python3.13/site-packages/OCP/OCP*.so | grep "not found"
```

The `OCP` wheel is a manylinux build, so the distribution itself is not a
compatibility concern. Rocky 9's glibc 2.34 is well above the wheel's baseline.

## Fetch the CAD from Git LFS

The STEP files are stored in Git LFS. If `git lfs install` did not run before the
clone, the working tree holds 130-byte text pointers instead of CAD, and the
error names a parser problem rather than a missing file:

```text
ValueError: Failed to read STEP file: cad/DSG-000046520/source.stp
**** ERR StepFile : Undefined Parsing: Line 2: Incorrect syntax: unexpected TYPE
```

Line 2 is the `oid sha256:` line of the pointer file. Fix it in place:

```bash
git lfs install
git lfs pull
```

Confirm real geometry rather than pointers:

```bash
ls -lh cad/*/source.stp
```

Expect roughly 89M and 7.2M. Anything near 130 bytes is still a pointer.

## Create the environment and verify

```bash
uv sync --all-extras
uv run pytest -q
```

The full suite is 114 tests and needs no CAD cache; it builds what it needs.

## Under WSL with interop disabled

A Rocky distro imported into WSL often has Windows interop switched off, which
means `/proc/sys/fs/binfmt_misc/WSLInterop` is absent and no `.exe` can be
executed even though `/mnt/c` is mounted and the files look executable.

Two consequences:

- The viewers do not open a browser tab by themselves. They print the URL
  instead, along with a LAN address, and `gio: Operation not supported` on the
  fallback attempt is harmless. Click the printed `http://localhost:7000`.
- `wsl.exe` cannot be used to reach a sibling distro. To move a decomposition
  cache from an Ubuntu distro on the same host, stage it through the shared
  Windows drive, which both distros can see:

  ```bash
  # in the Ubuntu distro
  tar -C ~/clones/Twin-Lab -czf /mnt/c/temp/twin-lab-cache.tgz .cache/twin_lab

  # in the Rocky distro
  tar -xzf /mnt/c/temp/twin-lab-cache.tgz -C ~/clones/Twin-Lab
  ```

  Use `tar` rather than a recursive copy. The decomposition is thousands of small
  hull OBJs and writing them individually across the 9p `/mnt/c` mount is slow.

A transferred cache stays valid across distros. Nothing machine-specific is
recorded: `CACHE_ROOT` is resolved relative to the repository, manifests store
bare file names, and staleness falls back to comparing `source_sha256` when
timestamps do not survive the copy.

To enable interop instead, add the following to `/etc/wsl.conf` in the distro and
run `wsl --shutdown` from Windows:

```ini
[interop]
enabled = true
appendWindowsPath = true
```
