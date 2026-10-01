"""Framework CLI: python -m framework --help."""

import argparse
import json
from pathlib import Path

from framework import JobManager, RunConfig, RunService
from framework.config import check_environment, expand_sweep


def main():
    parser = argparse.ArgumentParser(description="Optimizer experiment framework")
    parser.add_argument("--workspace", type=Path, default=Path(".optimizer-framework"))
    sub = parser.add_subparsers(dest="command", required=True)
    queue = sub.add_parser("queue")
    queue.add_argument("config", type=Path)
    queue.add_argument("--design", action="append")
    queue.add_argument("--sweep", type=Path, help="JSON object mapping settings to lists")
    sub.add_parser("jobs")
    sub.add_parser("recover")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("job_id")
    concurrency = sub.add_parser("concurrency")
    concurrency.add_argument("limit", type=int)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("run", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("runs", nargs="+", type=Path)
    report = sub.add_parser("report")
    report.add_argument("run", type=Path)
    report.add_argument("output", type=Path)
    check = sub.add_parser("check")
    check.add_argument("python")
    args = parser.parse_args()
    manager, service = JobManager(args.workspace), RunService()
    if args.command == "queue":
        config = RunConfig.from_dict(json.loads(args.config.read_text(encoding="utf-8")))
        axes = json.loads(args.sweep.read_text(encoding="utf-8")) if args.sweep else {}
        configs = expand_sweep(config, args.design or [config.input_dcp], axes)
        import uuid
        print(json.dumps(manager.enqueue(configs, batch_id=uuid.uuid4().hex if len(configs) > 1 else None)))
    elif args.command == "jobs":
        print(json.dumps(manager.list(), indent=2))
    elif args.command == "recover":
        manager.ensure_scheduler()
    elif args.command == "cancel":
        manager.cancel(args.job_id)
    elif args.command == "concurrency":
        manager.set_concurrency(args.limit)
    elif args.command == "inspect":
        print(json.dumps(service.monitor(service.snapshot(args.run)), indent=2))
    elif args.command == "compare":
        print(json.dumps(service.compare(args.runs), indent=2))
    elif args.command == "report":
        args.output.write_text(service.report(args.run), encoding="utf-8")
    elif args.command == "check":
        print(json.dumps(check_environment(args.python, manager.repository), indent=2))


if __name__ == "__main__":
    main()
