from __future__ import annotations

import argparse
import json
from pathlib import Path

from visiondata_gate.memory_governance_benchmark import (
    run_memory_governance_benchmark,
    verify_memory_governance_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--output", type=Path)
    operation.add_argument("--verify-existing", type=Path)
    args = parser.parse_args()
    if args.verify_existing is not None:
        source = args.verify_existing.expanduser().resolve(strict=True)
        result = json.loads(source.read_text(encoding="utf-8"))
        verify_memory_governance_benchmark(result)
        print(
            json.dumps(
                {
                    "verified": str(source),
                    "matrix_sha256": result["matrix_sha256"],
                    **result["governed"],
                },
                sort_keys=True,
            )
        )
        return 0

    result = run_memory_governance_benchmark()
    verify_memory_governance_benchmark(result)
    assert args.output is not None
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"output": str(target), **result["governed"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
