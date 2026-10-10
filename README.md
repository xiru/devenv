# devenv-check

Checks whether the current computer has the global tooling needed to develop,
test and run applications in:

| Environment | Required | Optional (reported as *partial* when missing) |
|---|---|---|
| Git | `git` (≥ 2.34) | global `user.name` / `user.email` |
| Java + Gradle | `java` (≥ 17), `javac` (a JDK, not just a JRE), `gradle` | `JAVA_HOME` set and valid |
| Go | `go` (≥ 1.22) | Go bin directory (`GOBIN` / `GOPATH/bin`) on `PATH` |
| JavaScript / TypeScript | `node` (≥ 22), `npm`, `npx` | global `tsc` |
| C / C++ | a C and a C++ compiler (gcc/g++, clang/clang++ or MSVC) | `cmake`, `make` or `ninja` |
| C# | .NET SDK (≥ 8) — a runtime alone is not enough | |
| Docker | `docker` CLI and a reachable engine/daemon | `docker compose` |
| Kubernetes | `kubectl` | current kube context, `helm`, `kind`/`minikube`/`k3d` |
| Visual Studio Code | `code`, plus the main extension per language (see below), installed and up to date | ESLint, CMake Tools, WSL (Windows) |

### VS Code extensions

| Language | Extension (alternatives accepted) |
|---|---|
| Java | `vscjava.vscode-java-pack` (or `redhat.java`) |
| Gradle | `vscjava.vscode-gradle` |
| Go | `golang.go` |
| JavaScript / TypeScript | built into VS Code; `dbaeumer.vscode-eslint` optional |
| C / C++ | `ms-vscode.cpptools-extension-pack` (or `ms-vscode.cpptools`); `ms-vscode.cmake-tools` optional |
| C# | `ms-dotnettools.csdevkit` (or `ms-dotnettools.csharp`) |
| Docker | `ms-azuretools.vscode-containers` (or `ms-azuretools.vscode-docker`) |
| Kubernetes | `ms-kubernetes-tools.vscode-kubernetes-tools` |
| WSL (Windows only) | `ms-vscode-remote.remote-wsl` optional |

Installed extensions are read from `~/.vscode/extensions` (inside WSL: `~/.vscode-server/extensions`,
i.e. the extensions VS Code uses for that distro), so the editor is never launched for this.
"Up to date" is checked against the Visual Studio Marketplace: a stable install is compared with
the newest stable release, a pre-release install with the newest pre-release. VS Code itself is
compared with the latest stable release. Missing/outdated extensions get a ready-to-run
`code --install-extension … [--force]` command. Use `--offline` to skip these network checks; a
network failure is reported but never fails the check.

When something is missing it prints install commands for the detected OS.

**Primary targets** (tested on real machines):

- **Windows 11** — winget package IDs (verified against the winget catalog); scoop/choco for
  Gradle, which is not in winget; MSVC Build Tools detected through `vswhere`.
- **Ubuntu** — apt for system packages; SDKMAN!, nvm and the official Go tarball/snap where
  Ubuntu's packages lag behind upstream.
- **WSL running Ubuntu** — detected automatically. Windows binaries leaking in through the
  WSL PATH (e.g. `/mnt/c/Program Files/nodejs/npm`) are flagged, Docker Desktop with WSL
  integration is the recommended Docker/Kubernetes setup, and the Docker Desktop stub is
  recognised ("WSL integration is off for this distro").

Also covered: macOS (Homebrew), Fedora/RHEL (dnf), Arch (pacman), openSUSE (zypper), and
distro‑independent installers for any other Linux.

Only the Python standard library is used (Python 3.11+, developed on 3.14).

## Usage

From the project folder:

```bash
python3 -m devenv_check
```

On Windows use `python` or `py` instead of `python3` if that is how Python is exposed.

Options:

```
--deep             also build and run a hello world program in every environment
--only java,go     check a subset: git, java, go, node, cpp, dotnet, docker, kubernetes, vscode
--offline          skip VS Code / extension update checks (no network access)
--json             machine readable output (includes the fix commands)
-v, --verbose      show where each tool was found
--no-hints         skip installation suggestions
--no-color         plain output (NO_COLOR is honored too)
--strict           exit non-zero on warnings, not only on missing tools
```

Exit code is `0` when every environment is at least partially usable, `1` when any
required tool is missing — handy for CI or onboarding scripts.

To have a `devenv-check` command available everywhere:

```bash
python3 -m pip install .
```

## Deep mode: hello world build & run

`python3 -m devenv_check --deep` proves each toolchain actually works by building and
running a tiny program in a temporary directory (deleted afterwards):

| Environment | Hello world tests |
|---|---|
| Git | `init`, `add`, `commit`, `log` in a temporary repository (your hooks, signing and identity settings are bypassed) |
| Java + Gradle | `javac` + `java`; a Gradle `application` project via `gradle run --offline --no-daemon` |
| Go | `go build` of a module (with `GOTOOLCHAIN=local`, so no toolchain download) + run |
| JavaScript / TypeScript | `node hello.js`; `hello.ts` compiled with a global `tsc`, or run with Node's built-in type stripping (Node ≥ 22.6) |
| C / C++ | compile + run with gcc/g++, clang/clang++, or MSVC (loads `vcvars64.bat` automatically when `cl.exe` isn't on PATH) |
| C# | `dotnet build` + `dotnet run` of a console project targeting the newest SDK |
| Docker | `docker build` of a `FROM hello-world` image, `docker run`, then the image is removed |
| Kubernetes | a `busybox` pod that echoes and is removed (`kubectl run --rm`) — **only** on local clusters (docker-desktop, kind-\*, minikube, k3d-\*, rancher-desktop, …). Any other context gets a server-side dry run, so nothing is ever created in a shared cluster |

Each environment header shows `hello world: N/N passed`, `N failed`, or `skipped` (when the
toolchain is missing, which the installation rows already explain). A failed build marks the
environment as MISSING; `-v` prints the command log of failed tests. Docker and Kubernetes
tests need internet access the first time to pull `hello-world` / `busybox`.

## Notes

- Checks run in parallel; `gradle --version` and `docker info` are the slow ones.
- On macOS the checker avoids running `gcc`/`clang`/`java` stubs that would pop up
  an installer dialog, by asking `xcode-select -p` / `java_home` first.
- On Windows, MSVC is detected through `vswhere.exe` even when `cl.exe` is not on
  `PATH` (it normally only is inside a "Developer PowerShell for VS").
- Minimum versions live in `MIN_VERSIONS` in `devenv_check/checks.py`; install
  commands live in `devenv_check/install_hints.py` (lookup order: WSL → distro family →
  generic Linux); hello world tests live in `devenv_check/smoke.py`.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
