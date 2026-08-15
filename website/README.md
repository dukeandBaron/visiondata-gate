# Judge website

This directory contains the dependency-free static reviewer demo for VisionData Gate.
It visualizes the frozen `Omni-180-v1` public pilot and does not execute a new Gate run
inside the browser. The complete local Runtime, REST API, tests, and redacted evidence
remain in the repository root.

Serve the repository root for local review:

```powershell
python -m http.server 4173
```

Then open `http://127.0.0.1:4173/website/`.

`data/site-data.json` is a presentation projection of the signed release artifacts. Run
`python tools/check_website_data.py` before deployment to ensure its denominators,
dynamic triggers, checks, and receipt digest still match the release.
