# Flexiconv desktop apps

This folder is the place for **releaseable desktop app builds** of the Flexiconv GUI (flexiConv): standalone installers that run without installing Python.

| Platform | File | Notes |
|----------|------|--------|
| **macOS** | `flexiConv.dmg` | Open the DMG and drag flexiConv to Applications. |
| **Windows** | *(planned)* | One-file or one-folder `.exe` build. |
| **Linux** | *(planned)* | AppDir or AppImage. |

## Download

Get the latest builds from [GitHub Releases](https://github.com/ufal/flexiconv/releases) (attach the built files to a release). When no release is published yet, build from source (see below).

## Building the apps

Builds are produced from the **`gui/`** project in this repo. See `gui/README.md` for details.

- **macOS:** From the repo root, run `./gui/build_mac_app.sh`. Outputs: `gui/dist/flexiConv.app` and `gui/dist/flexiConv.dmg`. Copy `flexiConv.dmg` here for release.
- **Windows / Linux:** Use the same `gui/` project with PyInstaller on the target OS (see `dev/GUI-DEPLOYMENT.md`). Copy the resulting installer or folder here for release.

You can copy built artifacts into `apps/` when preparing a release, then attach them to a GitHub Release. The `apps/` folder can stay in git as a placeholder (with this README); binary installers are often not committed and are only published via Releases.
