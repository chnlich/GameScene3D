# GameFrame3D

GameFrame3D aims to turn image and text inputs into generated 3D scenes that can
be inspected in a browser and downloaded with generation evidence.

This GameScene3D repository is an initial foundation. End-to-end implementation
is not yet complete. It currently contains the shared interface and empty
work-line baselines; application code and demo materials will follow.

The shared interface is defined in `contracts/scene.schema.json`. Consumers use
this contract as the single source for HTTP payloads and the Python generation
boundary.

| Work line | Owned directories and files | Branch |
| --- | --- | --- |
| Engineering | Root configuration, dependency locks and run entry point; `server/`; `contracts/` | `work/engineering` |
| Generation | `pipeline/` | `work/generation` |
| Viewer | `web/` | `work/viewer` |
| Materials | `demo/` | `work/demo` |

The work branches start at the same foundation commit and are independent
reviewer merge targets. Only the engineering session integrates `main`.
Ownership directories are reserved; implementation files are not present yet.
