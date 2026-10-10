"""Per-OS installation suggestions.

HINTS[family][key] is a list of lines (commands or short notes). Lookup falls
back from the distro family to the generic "linux" table, and finally to the
official documentation link in DOCS. `{arch}` is replaced with amd64/arm64.
"""

from __future__ import annotations

from .platform_info import PlatformInfo
from .runner import which

DOCS: dict[str, str] = {
    "java": "https://adoptium.net/installation/",
    "java_home": "https://docs.oracle.com/en/java/javase/21/install/",
    "gradle": "https://gradle.org/install/",
    "go": "https://go.dev/doc/install",
    "go_path": "https://go.dev/doc/code#Command",
    "node": "https://nodejs.org/en/download",
    "typescript": "https://www.typescriptlang.org/download/",
    "cpp": "https://code.visualstudio.com/docs/languages/cpp",
    "build_tools": "https://cmake.org/download/",
    "dotnet": "https://learn.microsoft.com/dotnet/core/install/",
    "docker": "https://docs.docker.com/get-started/get-docker/",
    "docker_daemon": "https://docs.docker.com/engine/daemon/start/",
    "docker_compose": "https://docs.docker.com/compose/install/",
    "kubectl": "https://kubernetes.io/docs/tasks/tools/",
    "kube_context": "https://kind.sigs.k8s.io/docs/user/quick-start/",
    "helm": "https://helm.sh/docs/intro/install/",
    "local_cluster": "https://kind.sigs.k8s.io/docs/user/quick-start/#installation",
}

_NPM_TS = ["npm install -g typescript"]
_K8S_LOCAL = ["kind create cluster   (or: minikube start, or enable Kubernetes in Docker Desktop)"]

HINTS: dict[str, dict[str, list[str]]] = {
    "windows": {
        "java": ["winget install --id EclipseAdoptium.Temurin.21.JDK -e"],
        "java_home": [
            "# PowerShell; asks java for its real home, which also works with Oracle's javapath shims:",
            "$h = ((java -XshowSettings:properties -version 2>&1 | Out-String) -split \"`n\" | Select-String 'java.home').ToString().Split('=')[1].Trim()",
            '[Environment]::SetEnvironmentVariable("JAVA_HOME", $h, "User")   # then open a new terminal',
        ],
        "gradle": [
            "scoop install gradle   (or: choco install gradle)",
            "# projects that ship a Gradle wrapper can use .\\gradlew.bat instead",
        ],
        "go": ["winget install --id GoLang.Go -e"],
        "go_path": [
            '[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$(go env GOPATH)\\bin", "User")',
        ],
        "node": ["winget install --id OpenJS.NodeJS.LTS -e"],
        "typescript": _NPM_TS,
        "cpp": [
            'winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"',
            "# then build from 'Developer PowerShell for VS' so cl.exe is on PATH",
            "# GCC alternative: winget install --id MSYS2.MSYS2 -e, then in the UCRT64 shell: pacman -S mingw-w64-ucrt-x86_64-toolchain",
        ],
        "build_tools": ["winget install --id Kitware.CMake -e", "winget install --id Ninja-build.Ninja -e"],
        "dotnet": ["winget install --id Microsoft.DotNet.SDK.10 -e"],
        "docker": ["wsl --install   (Docker Desktop needs WSL 2; reboot if asked)", "winget install --id Docker.DockerDesktop -e"],
        "docker_daemon": ["Start Docker Desktop and wait for 'Engine running'"],
        "docker_compose": ["Compose ships with Docker Desktop: update Docker Desktop"],
        "kubectl": ["winget install --id Kubernetes.kubectl -e"],
        "kube_context": _K8S_LOCAL,
        "helm": ["winget install --id Helm.Helm -e"],
        "local_cluster": ["winget install --id Kubernetes.kind -e   (or: winget install --id Kubernetes.minikube -e)"],
    },
    "macos": {
        "java": ["brew install --cask temurin@21"],
        "java_home": ["echo 'export JAVA_HOME=$(/usr/libexec/java_home)' >> ~/.zshrc"],
        "gradle": ["brew install gradle"],
        "go": ["brew install go"],
        "go_path": ["echo 'export PATH=\"$PATH:$(go env GOPATH)/bin\"' >> ~/.zshrc"],
        "node": ["brew install node"],
        "typescript": _NPM_TS,
        "cpp": ["xcode-select --install"],
        "build_tools": ["brew install cmake ninja"],
        "dotnet": ["brew install --cask dotnet-sdk"],
        "docker": ["brew install --cask docker   (Docker Desktop)", "# lightweight alternative: brew install colima docker && colima start"],
        "docker_daemon": ["open -a Docker   (or: colima start)"],
        "docker_compose": ["brew install docker-compose"],
        "kubectl": ["brew install kubectl"],
        "kube_context": _K8S_LOCAL,
        "helm": ["brew install helm"],
        "local_cluster": ["brew install kind   (or: brew install minikube)"],
    },
    # Generic Linux: distro-independent installers, used when a family has no entry.
    "linux": {
        "java": ['curl -s "https://get.sdkman.io" | bash', "sdk install java 21-tem"],
        "java_home": [
            "echo \"export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | awk -F' = ' '/java.home/ {print $2}')\" >> ~/.bashrc",
        ],
        "gradle": [
            '# distro packages are often outdated; SDKMAN! installs current releases',
            'curl -s "https://get.sdkman.io" | bash',
            "sdk install gradle",
        ],
        "go": [
            "curl -LO \"https://go.dev/dl/$(curl -s 'https://go.dev/VERSION?m=text' | head -n1).linux-{arch}.tar.gz\"",
            "sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go*.linux-{arch}.tar.gz",
            "echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc",
        ],
        "go_path": ["echo 'export PATH=\"$PATH:$(go env GOPATH)/bin\"' >> ~/.bashrc"],
        "node": ["curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash", "nvm install --lts"],
        "typescript": _NPM_TS,
        "cpp": ["Install gcc, g++ and make with your distribution's package manager"],
        "build_tools": ["Install cmake and ninja (or make) with your distribution's package manager"],
        "dotnet": ["curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel LTS", "echo 'export PATH=$PATH:$HOME/.dotnet' >> ~/.bashrc"],
        "docker": ["curl -fsSL https://get.docker.com | sudo sh"],
        "docker_daemon": ["sudo systemctl enable --now docker", "sudo usermod -aG docker $USER   (then log out and back in)"],
        "docker_compose": ["Install the docker-compose-plugin package from Docker's repository (get.docker.com includes it)"],
        "kubectl": [
            'curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/{arch}/kubectl"',
            "sudo install -m 0755 kubectl /usr/local/bin/kubectl",
        ],
        "kube_context": _K8S_LOCAL,
        "helm": ["curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"],
        "local_cluster": [
            "curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-{arch}",
            "sudo install minikube-linux-{arch} /usr/local/bin/minikube",
        ],
    },
    # Debian / Ubuntu (also used inside WSL running Ubuntu, below the "wsl" table).
    "debian": {
        "java": ["sudo apt update && sudo apt install -y openjdk-21-jdk   (use openjdk-17-jdk on older releases)"],
        "gradle": [
            "# Ubuntu's gradle package is very old; SDKMAN! installs current releases",
            "sudo apt install -y curl zip unzip",
            'curl -s "https://get.sdkman.io" | bash',
            'source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk install gradle',
        ],
        "go": [
            "sudo snap install go --classic   (Ubuntu; in WSL this needs systemd enabled)",
            "# or the official tarball, always the latest release:",
            "curl -LO \"https://go.dev/dl/$(curl -s 'https://go.dev/VERSION?m=text' | head -n1).linux-{arch}.tar.gz\"",
            "sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go*.linux-{arch}.tar.gz",
            "echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc",
        ],
        "node": [
            "# Ubuntu's nodejs package lags behind; nvm installs the current LTS",
            "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash",
            'source ~/.nvm/nvm.sh && nvm install --lts',
        ],
        "cpp": ["sudo apt update && sudo apt install -y build-essential gdb"],
        "build_tools": ["sudo apt install -y cmake ninja-build"],
        "dotnet": [
            "sudo apt update && sudo apt install -y dotnet-sdk-8.0",
            "# newer SDKs on Ubuntu LTS: sudo add-apt-repository ppa:dotnet/backports && sudo apt install -y dotnet-sdk-10.0",
        ],
        "docker_compose": ["sudo apt install -y docker-compose-plugin"],
        "kubectl": ["sudo snap install kubectl --classic   (Ubuntu; or the curl method from kubernetes.io)"],
        "helm": ["sudo snap install helm --classic   (Ubuntu; or the get-helm-3 script from helm.sh)"],
    },
    # Linux under WSL: Docker and Kubernetes usually come from Docker Desktop on the Windows side.
    "wsl": {
        "docker": [
            "# Recommended: Docker Desktop on Windows, shared with WSL. In PowerShell on Windows:",
            "winget install --id Docker.DockerDesktop -e",
            "# then Docker Desktop > Settings > Resources > WSL integration > enable this distro",
            "# Alternative, an engine inside WSL only: curl -fsSL https://get.docker.com | sudo sh",
        ],
        "docker_daemon": [
            "Docker Desktop: start it on Windows and enable Settings > Resources > WSL integration for this distro",
            "Engine inside WSL: sudo systemctl enable --now docker   (without systemd: sudo service docker start)",
            "sudo usermod -aG docker $USER   (then run 'wsl --shutdown' in Windows and reopen the terminal)",
        ],
        "docker_compose": ["Included with Docker Desktop's WSL integration; for an engine inside WSL: sudo apt install -y docker-compose-plugin"],
        "kube_context": [
            "Enable Kubernetes in Docker Desktop (Settings > Kubernetes); its context is shared with WSL",
            "or create a local cluster: kind create cluster",
        ],
        "go": [
            "# snap needs systemd in WSL; the official tarball always works:",
            "curl -LO \"https://go.dev/dl/$(curl -s 'https://go.dev/VERSION?m=text' | head -n1).linux-{arch}.tar.gz\"",
            "sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go*.linux-{arch}.tar.gz",
            "echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc",
        ],
    },
    "fedora": {
        "java": ["sudo dnf install -y java-21-openjdk-devel"],
        "go": ["sudo dnf install -y golang"],
        "node": ["sudo dnf install -y nodejs npm"],
        "cpp": ["sudo dnf install -y gcc gcc-c++ make"],
        "build_tools": ["sudo dnf install -y cmake ninja-build"],
        "dotnet": ["sudo dnf install -y dotnet-sdk-8.0"],
        "docker_compose": ["sudo dnf install -y docker-compose-plugin"],
        "kubectl": ["sudo dnf install -y kubernetes-client"],
        "helm": ["sudo dnf install -y helm"],
    },
    "arch": {
        "java": ["sudo pacman -S --needed jdk21-openjdk"],
        "gradle": ["sudo pacman -S --needed gradle"],
        "go": ["sudo pacman -S --needed go"],
        "node": ["sudo pacman -S --needed nodejs npm"],
        "typescript": ["sudo pacman -S --needed typescript"],
        "cpp": ["sudo pacman -S --needed base-devel"],
        "build_tools": ["sudo pacman -S --needed cmake ninja"],
        "dotnet": ["sudo pacman -S --needed dotnet-sdk"],
        "docker": ["sudo pacman -S --needed docker docker-compose"],
        "docker_compose": ["sudo pacman -S --needed docker-compose"],
        "kubectl": ["sudo pacman -S --needed kubectl"],
        "helm": ["sudo pacman -S --needed helm"],
        "local_cluster": ["sudo pacman -S --needed minikube"],
    },
    "suse": {
        "java": ["sudo zypper install -y java-21-openjdk-devel"],
        "go": ["sudo zypper install -y go"],
        "node": ["sudo zypper install -y nodejs-default npm-default"],
        "cpp": ["sudo zypper install -y gcc gcc-c++ make"],
        "build_tools": ["sudo zypper install -y cmake ninja"],
        "docker": ["sudo zypper install -y docker docker-compose"],
        "docker_compose": ["sudo zypper install -y docker-compose"],
        "kubectl": ["sudo zypper install -y kubernetes-client"],
        "helm": ["sudo zypper install -y helm"],
    },
}

# Git and Visual Studio Code, merged into the tables above.
_GIT_IDENTITY = ['git config --global user.name "Your Name"', 'git config --global user.email "you@example.com"']
_VSCODE_REPO_RPM = [
    "sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc",
    'echo -e "[code]\\nname=Visual Studio Code\\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\\nenabled=1\\n'
    'gpgcheck=1\\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc" | sudo tee /etc/yum.repos.d/vscode.repo',
]
_EXTRA_HINTS: dict[str, dict[str, list[str]]] = {
    "windows": {
        "git": ["winget install --id Git.Git -e"],
        "git_identity": _GIT_IDENTITY,
        "vscode": ["winget install --id Microsoft.VisualStudioCode -e"],
        "vscode_path": [
            "Re-run the VS Code installer with 'Add to PATH' checked, or add this folder to your user PATH:",
            "%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\bin",
        ],
        "vscode_update": ["winget upgrade --id Microsoft.VisualStudioCode -e   (or in VS Code: Help > Check for Updates)"],
    },
    "macos": {
        "git": ["xcode-select --install   (or: brew install git)"],
        "git_identity": _GIT_IDENTITY,
        "vscode": ["brew install --cask visual-studio-code"],
        "vscode_path": ["In VS Code: Command Palette > \"Shell Command: Install 'code' command in PATH\""],
        "vscode_update": ["brew upgrade --cask visual-studio-code   (or: Code > Check for Updates)"],
    },
    "linux": {
        "git": ["Install git with your distribution's package manager"],
        "git_identity": _GIT_IDENTITY,
        "vscode": ["Download the .deb/.rpm or tarball from https://code.visualstudio.com/download"],
        "vscode_path": ["Add the folder containing the 'code' launcher (e.g. /usr/share/code/bin) to PATH"],
        "vscode_update": ["Download the latest release from https://code.visualstudio.com/download"],
    },
    "debian": {
        "git": ["sudo apt update && sudo apt install -y git"],
        "vscode": [
            "sudo snap install code --classic",
            "# or download the .deb from https://code.visualstudio.com/download and: sudo apt install ./code_*.deb",
        ],
        "vscode_update": ["sudo snap refresh code   (.deb installs: sudo apt update && sudo apt install --only-upgrade code)"],
    },
    "fedora": {
        "git": ["sudo dnf install -y git"],
        "vscode": _VSCODE_REPO_RPM + ["sudo dnf install -y code"],
        "vscode_update": ["sudo dnf upgrade -y code"],
    },
    "arch": {
        "git": ["sudo pacman -S --needed git"],
        "vscode": ["yay -S visual-studio-code-bin   (AUR, Microsoft build; or: sudo pacman -S code for the open-source build)"],
        "vscode_update": ["yay -Syu visual-studio-code-bin"],
    },
    "suse": {
        "git": ["sudo zypper install -y git"],
        "vscode": [_VSCODE_REPO_RPM[0],
                   "sudo zypper addrepo https://packages.microsoft.com/yumrepos/vscode vscode",
                   "sudo zypper refresh && sudo zypper install -y code"],
        "vscode_update": ["sudo zypper update -y code"],
    },
    "wsl": {
        "git": [
            "sudo apt update && sudo apt install -y git",
            "# optional, reuse Windows credentials (Git for Windows installed):",
            'git config --global credential.helper "/mnt/c/Program\\ Files/Git/mingw64/bin/git-credential-manager.exe"',
        ],
        "vscode": [
            "# Install VS Code on Windows, not inside WSL. In PowerShell on Windows:",
            "winget install --id Microsoft.VisualStudioCode -e",
            "code --install-extension ms-vscode-remote.remote-wsl",
            "# then open a new WSL terminal and run: code .",
        ],
        "vscode_update": ["Update VS Code on Windows (Help > Check for Updates); the WSL server follows automatically"],
    },
}
for _family, _extra in _EXTRA_HINTS.items():
    HINTS.setdefault(_family, {}).update(_extra)

DOCS.update({
    "git": "https://git-scm.com/downloads",
    "git_identity": "https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup",
    "vscode": "https://code.visualstudio.com/docs/setup/setup-overview",
    "vscode_path": "https://code.visualstudio.com/docs/setup/setup-overview",
    "vscode_update": "https://code.visualstudio.com/updates",
})

# Bash scripting, Kotlin and Rust, merged into the tables above.
_SDKMAN_KOTLIN = ['curl -s "https://get.sdkman.io" | bash', 'source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk install kotlin']
_RUSTUP_UNIX = ["curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y", '. "$HOME/.cargo/env"']
_RUST_COMPONENTS = ["rustup component add clippy rustfmt"]
_LANG_HINTS: dict[str, dict[str, list[str]]] = {
    "windows": {
        "bash": ["winget install --id Git.Git -e   (includes Git Bash)", "# or Linux bash through WSL: wsl --install -d Ubuntu"],
        "shell_tools": ["winget install --id koalaman.shellcheck -e", "winget install --id mvdan.shfmt -e"],
        "kotlin": ["scoop install kotlin   (or: choco install kotlinc)", "# kotlinc needs a JDK (see Java + Gradle)"],
        "rust": [
            "winget install --id Rustlang.Rustup -e",
            "rustup default stable",
            "# the default MSVC toolchain links with the Visual Studio C++ Build Tools (see C / C++)",
        ],
        "rustup": ["winget install --id Rustlang.Rustup -e"],
        "rust_components": _RUST_COMPONENTS,
    },
    "macos": {
        "bash": ["brew install bash   (macOS ships bash 3.2; Homebrew installs bash 5)"],
        "shell_tools": ["brew install shellcheck shfmt"],
        "kotlin": ["brew install kotlin"],
        "rust": ["xcode-select --install   (provides the linker)", *_RUSTUP_UNIX],
        "rustup": ["brew install rustup && rustup-init -y"],
        "rust_components": _RUST_COMPONENTS,
    },
    "linux": {
        "bash": ["Install bash with your distribution's package manager"],
        "shell_tools": ["Install shellcheck and shfmt with your package manager (shfmt: go install mvdan.cc/sh/v3/cmd/shfmt@latest)"],
        "kotlin": ["# needs zip/unzip/curl; kotlinc also needs a JDK (see Java + Gradle)", *_SDKMAN_KOTLIN],
        "rust": ["# a C linker is required too: install gcc (see C / C++)", *_RUSTUP_UNIX],
        "rustup": ["# distro Rust packages lag behind; rustup installs and updates official toolchains", *_RUSTUP_UNIX],
        "rust_components": _RUST_COMPONENTS,
    },
    "debian": {
        "bash": ["sudo apt update && sudo apt install -y bash"],
        "shell_tools": ["sudo apt install -y shellcheck shfmt"],
        "kotlin": ["sudo apt install -y curl zip unzip", *_SDKMAN_KOTLIN, "# or: sudo snap install kotlin --classic"],
        "rust": ["sudo apt update && sudo apt install -y build-essential curl", *_RUSTUP_UNIX],
    },
    "fedora": {
        "bash": ["sudo dnf install -y bash"],
        "shell_tools": ["sudo dnf install -y ShellCheck shfmt"],
        "rust": ["sudo dnf install -y gcc curl", *_RUSTUP_UNIX],
    },
    "arch": {
        "bash": ["sudo pacman -S --needed bash"],
        "shell_tools": ["sudo pacman -S --needed shellcheck shfmt"],
        "kotlin": ["sudo pacman -S --needed kotlin"],
        "rust": ["sudo pacman -S --needed rustup base-devel && rustup default stable"],
        "rustup": ["sudo pacman -S --needed rustup && rustup default stable"],
    },
    "suse": {
        "bash": ["sudo zypper install -y bash"],
        "shell_tools": ["sudo zypper install -y ShellCheck shfmt"],
        "rust": ["sudo zypper install -y gcc curl", *_RUSTUP_UNIX],
    },
}
for _family, _extra in _LANG_HINTS.items():
    HINTS.setdefault(_family, {}).update(_extra)

DOCS.update({
    "bash": "https://www.gnu.org/software/bash/",
    "shell_tools": "https://www.shellcheck.net/",
    "kotlin": "https://kotlinlang.org/docs/command-line.html",
    "rust": "https://www.rust-lang.org/tools/install",
    "rustup": "https://rust-lang.github.io/rustup/installation/index.html",
    "rust_components": "https://rust-lang.github.io/rustup/concepts/components.html",
})

# Dart and Flutter, merged into the tables above.
_FLUTTER_GIT_UNIX = [
    "git clone https://github.com/flutter/flutter.git -b stable ~/flutter",
    "echo 'export PATH=\"$PATH:$HOME/flutter/bin\"' >> ~/.bashrc && source ~/.bashrc",
    "flutter doctor",
]
_FLUTTER_DOCTOR = [
    "flutter doctor -v   (explains how to fix each item)",
    "flutter doctor --android-licenses   (accept the Android SDK licenses, if you target Android)",
]
_DART_FLUTTER_HINTS: dict[str, dict[str, list[str]]] = {
    "windows": {
        "dart": ["winget install --id Google.DartSDK -e", "# or install Flutter, which bundles Dart"],
        "flutter": [
            "# Flutter is not in winget; the official git checkout (needs Git):",
            'git clone https://github.com/flutter/flutter.git -b stable "$env:USERPROFILE\\flutter"',
            '[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\\flutter\\bin", "User")',
            "# open a new terminal, then: flutter doctor",
        ],
        "flutter_doctor": _FLUTTER_DOCTOR,
    },
    "macos": {
        "dart": ["brew tap dart-lang/dart && brew install dart", "# or install Flutter, which bundles Dart"],
        "flutter": ["brew install --cask flutter", "flutter doctor"],
        "flutter_doctor": _FLUTTER_DOCTOR,
    },
    "linux": {
        "dart": ["Download the Dart SDK from https://dart.dev/get-dart/archive, or install Flutter (it bundles Dart)"],
        "flutter": ["# prerequisites: git curl unzip xz-utils zip", *_FLUTTER_GIT_UNIX],
        "flutter_doctor": _FLUTTER_DOCTOR,
    },
    "debian": {
        "dart": [
            "sudo apt update && sudo apt install -y apt-transport-https wget gpg",
            "wget -qO- https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/dart.gpg",
            "echo 'deb [signed-by=/usr/share/keyrings/dart.gpg arch={arch}] "
            "https://storage.googleapis.com/download.dartlang.org/linux/debian stable main' | sudo tee /etc/apt/sources.list.d/dart_stable.list",
            "sudo apt update && sudo apt install -y dart",
            "# or install Flutter, which bundles Dart",
        ],
        "flutter": [
            "sudo apt update && sudo apt install -y curl git unzip xz-utils zip libglu1-mesa",
            *_FLUTTER_GIT_UNIX,
            "# or: sudo snap install flutter --classic",
            "# Linux desktop targets also need: sudo apt install -y clang cmake ninja-build pkg-config libgtk-3-dev",
        ],
    },
    "arch": {
        "dart": ["sudo pacman -S --needed dart"],
    },
    "wsl": {
        "flutter": [
            "# Flutter inside WSL builds web, Linux and Android (via adb) apps; for Windows desktop apps",
            "# or the Android emulator, install Flutter on Windows as well.",
            "sudo apt update && sudo apt install -y curl git unzip xz-utils zip libglu1-mesa",
            *_FLUTTER_GIT_UNIX,
        ],
    },
}
for _family, _extra in _DART_FLUTTER_HINTS.items():
    HINTS.setdefault(_family, {}).update(_extra)

# IntelliJ IDEA: the recommended IDE for Java and Kotlin (VS Code is not suggested for JVM work).
_TOOLBOX = "# or JetBrains Toolbox, which installs and updates all JetBrains IDEs: https://www.jetbrains.com/toolbox-app/"
_INTELLIJ_UPDATE = ["Update from JetBrains Toolbox, or in IntelliJ IDEA: Help > Check for Updates"]
_INTELLIJ_HINTS: dict[str, dict[str, list[str]]] = {
    "windows": {
        "intellij": ["winget install --id JetBrains.IntelliJIDEA -e",
                     "# or: winget install --id JetBrains.Toolbox -e   (then install IntelliJ IDEA from Toolbox)"],
        "intellij_update": _INTELLIJ_UPDATE,
    },
    "macos": {
        "intellij": ["brew install --cask intellij-idea", "# or: brew install --cask jetbrains-toolbox"],
        "intellij_update": ["brew upgrade --cask intellij-idea   (or update from JetBrains Toolbox / Help > Check for Updates)"],
    },
    "linux": {
        "intellij": ["Install JetBrains Toolbox (https://www.jetbrains.com/toolbox-app/) and IntelliJ IDEA from it",
                     "# or download IntelliJ IDEA from https://www.jetbrains.com/idea/download/"],
        "intellij_update": _INTELLIJ_UPDATE,
    },
    "debian": {
        "intellij": ["sudo snap install intellij-idea-ultimate --classic", _TOOLBOX],
        "intellij_update": ["sudo snap refresh intellij-idea-ultimate   (or update from JetBrains Toolbox)"],
    },
    "wsl": {
        "intellij": [
            "# Install IntelliJ IDEA on Windows and open projects stored in WSL through its WSL support.",
            "# In PowerShell on Windows:",
            "winget install --id JetBrains.IntelliJIDEA -e",
        ],
        "intellij_update": ["Update IntelliJ IDEA on Windows (JetBrains Toolbox or Help > Check for Updates)"],
    },
}
for _family, _extra in _INTELLIJ_HINTS.items():
    HINTS.setdefault(_family, {}).update(_extra)

DOCS.update({
    "dart": "https://dart.dev/get-dart",
    "flutter": "https://docs.flutter.dev/get-started/install",
    "flutter_doctor": "https://docs.flutter.dev/get-started/install",
    "intellij": "https://www.jetbrains.com/idea/download/",
    "intellij_update": "https://www.jetbrains.com/help/idea/update.html",
})

PACKAGE_MANAGER_LABEL = {
    "windows": "winget",
    "macos": "Homebrew",
    "debian": "apt",
    "fedora": "dnf",
    "arch": "pacman",
    "suse": "zypper",
    "linux": "generic installers",
}


def manager_label(platform: PlatformInfo) -> str:
    label = PACKAGE_MANAGER_LABEL.get(platform.family, platform.family)
    return f"{label} inside WSL" if platform.wsl else label


def hint_for(key: str, platform: PlatformInfo) -> list[str]:
    """Installation lines for `key` on this platform (may be empty).

    Lookup order: WSL-specific, distro family, then generic Linux.
    """
    tables = (["wsl"] if platform.wsl else []) + [platform.family] + (["linux"] if platform.system == "linux" else [])
    for table in tables:
        lines = HINTS.get(table, {}).get(key)
        if lines is not None:
            return [line.replace("{arch}", platform.arch) for line in lines]
    return []


def prerequisite_notes(platform: PlatformInfo) -> list[str]:
    """Things to know before running the suggested commands."""
    notes = []
    if platform.family == "windows" and which("winget") is None:
        notes.append("winget not found: install/update 'App Installer' from the Microsoft Store.")
    if platform.family == "macos" and which("brew") is None:
        notes.append('Homebrew not found: /bin/bash -c "$(curl -fsSL '
                     'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
    if platform.system == "linux" and which("curl") is None:
        notes.append("curl not found and several commands below need it: "
                     + ("sudo apt install -y curl" if platform.family == "debian" else "install curl first"))
    if platform.wsl:
        notes.append("Running inside WSL: tools installed on Windows are not used here (except Docker Desktop "
                     "via WSL integration); install the Linux versions inside this distro.")
    return notes
