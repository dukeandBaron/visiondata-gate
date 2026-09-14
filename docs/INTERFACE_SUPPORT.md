# Which interface should I use?

**The React workbench in `web/` is the primary interactive product.** Start there
for image/dataset import, annotation review, tasks, CAPA, evidence and learning.
It consumes the local FastAPI contracts. A successful page render is not evidence
that a backend, external connector or factory system is connected.

| Surface | Role | Maintenance and authority boundary |
| --- | --- | --- |
| React workbench | Primary desktop-browser UI | New interactive workflows go here; reads/writes require the actual local API and session. |
| Tauri host | Optional desktop wrapper of React | Not a separate fourth UI; install/upgrade/signing validation is specific to each built artifact. |
| Streamlit `app.py` | Legacy/compatibility analysis and historical demonstration | Retained for existing workflows and frozen evidence. Not the default entry for new product features; no feature-parity promise. |
| `reviewer_server.py` | Evidence projection / reviewer service | A supporting service, not a competing general-purpose operator interface. Its stored/replayed evidence is not new execution. |
| GitHub Pages | Public synthetic replay of the web experience | No private backend, uploaded customer images, login credentials, local training or production writes. |
| Python CLI | Headless deterministic processing and reproducibility | Useful without Node/Tauri; invoke only commands shown by `visiondata-gate --help`. |
| Spring gateway | Optional deployment gateway | Packaging-specific component; the source quickstart can use the local FastAPI/Vite path directly. |

## Platform support is not one boolean

- Windows is the primary local development and current desktop-preview target.
- The Python/React source quickstart uses portable commands; Linux/macOS execution
  must be evidenced on those systems. A Windows smoke pass does not certify them.
- Native macOS/Linux installers, signing/notarization, clean-machine acceptance
  and real NPU/CANN execution are not provided by adding a portable launcher.
- An older Windows installer does not automatically contain the latest `/learning`
  or other source-tree features. Check the package's own source/receipt binding.
- Local-only does not remove the need for session authentication. Do not turn on
  an insecure test-actor bypass to make a development command work.

## Choose an entry point

Use [Cross-platform quickstart](CROSS_PLATFORM_QUICKSTART.md) for current source,
[Running](RUNNING.md) for established Windows/isolated-reviewer workflows, and
[Publication boundary](PUBLICATION_BOUNDARY.md) before sharing any artifact.
New features should extend the primary web interface and shared contracts;
preserve old replay contracts instead of deleting their implementations merely
because a newer UI exists.
