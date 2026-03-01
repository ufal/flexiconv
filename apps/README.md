# Flexiconv desktop apps

This folder is the place for **releaseable desktop app builds** of the Flexiconv GUI (flexiConv): standalone installers that run without installing Python.

| Platform | File | Notes |
|----------|------|--------|
| **macOS** | `flexiConv.dmg` | Open the DMG and drag flexiConv to Applications. |
| **Windows** | `flexiConv.zip` (or folder) | Unzip and run `flexiConv.exe`. Built with `gui/build_win_exe.ps1` on Windows. |
| **Linux** | *(planned)* | AppDir or AppImage. |

## Download

Get the latest builds from [GitHub Releases](https://github.com/ufal/flexiconv/releases) (attach the built files to a release). When no release is published yet, build from source (see below).

## Building the apps

Builds are produced from the **`gui/`** project in this repo. See `gui/README.md` for details.

- **macOS:** From the repo root, run `./gui/build_mac_app.sh`. Outputs: `gui/dist/flexiConv.app` and `gui/dist/flexiConv.dmg`. Copy `flexiConv.dmg` here for release.
- **Windows:** Must be built on Windows (or on a Windows runner in CI). From the repo root in PowerShell: `.\gui\build_win_exe.ps1`. Outputs: `gui/dist/flexiConv/flexiConv.exe` and dependencies. Zip the `flexiConv` folder and attach to Releases.
- **Linux:** Use PyInstaller on Linux (see `dev/GUI-DEPLOYMENT.md`). Copy the resulting folder or AppImage here for release.

**Can I build the Windows .exe on a Mac?** No. PyInstaller does not cross-compile: you need to run the build on Windows (or use GitHub Actions / another CI with a Windows runner to produce the .exe and attach it to Releases). See **`dev/BUILDING-WINDOWS-ON-MAC.md`** for options: using a Windows VM on your Mac, getting the .exe back via Releases or Actions, and a ready-to-use GitHub Actions workflow.

You can copy built artifacts into `apps/` when preparing a release, then attach them to a GitHub Release. The `apps/` folder can stay in git as a placeholder (with this README); binary installers are often not committed and are only published via Releases.
