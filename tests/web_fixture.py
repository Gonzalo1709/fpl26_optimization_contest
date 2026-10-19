"""Disposable browser-test server; optimizer execution is the only stubbed boundary."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import uvicorn

from framework.web import create_app
from tools.create_gui_demo import create_demo


def main():
    with TemporaryDirectory(prefix="optimizer-browser-") as folder:
        root = Path(folder)
        create_demo(root / "history")
        (root / "fixture.dcp").write_bytes(b"synthetic checkpoint for queue tests")
        app = create_app(root / "jobs", [root / "history"])
        with patch.object(app.state.manager, "ensure_scheduler"):
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("OPTIMIZER_TEST_PORT", "8766")), log_level="warning")


if __name__ == "__main__":
    main()
