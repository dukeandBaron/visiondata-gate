from pathlib import Path
from tools.run_dynamic_benchmark_v4 import build_parser

ROOT = Path(__file__).resolve().parents[1]


def test_v4_default_input_is_the_public_frozen_benchmark():
    args = build_parser().parse_args([])
    assert (
        args.v3_report == ROOT / "benchmarks/DYNAMICBENCH_V3_REPLANNING_20260829.json"
    )
    assert args.v3_report.is_file()


def test_v4_default_output_does_not_overwrite_frozen_reference():
    args = build_parser().parse_args([])
    assert args.output == ROOT / "output/dynamicbench-v4/report.json"
    assert args.force is False
