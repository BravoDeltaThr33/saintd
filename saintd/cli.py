"""Command-line entry point: `saintd` starts the TUI; flags run maintenance."""

from __future__ import annotations

import argparse
import sys
import time

from . import APP_NAME, __version__


def _console_report():
    from .sync import Report
    state = {"stage": "", "t": 0.0}

    def stage(s):
        state["stage"] = s
        print(f"\n== {s}", flush=True)

    def progress(done, total, msg):
        now = time.monotonic()
        if now - state["t"] < 0.5 and done < total:
            return
        state["t"] = now
        pct = int(100 * done / total) if total else 100
        bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
        print(f"\r  [{bar}] {pct:3d}% {done}/{total} {msg[:40]:40}", end="", flush=True)

    def log(m):
        print(f"\n  {m}", flush=True)

    return Report(stage=stage, progress=progress, log=log)


def _print_wait(host: str, seconds: float) -> None:
    print(f"\n  {host} asked us to slow down; waiting {int(seconds)} s", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="saintd", description=f"{APP_NAME} — the saints of the Orthodox Church in your terminal.")
    p.add_argument("--version", action="version", version=f"saintd {__version__}")
    p.add_argument("--sync", action="store_true", help="build/refresh the directory from the APIs, then exit")
    p.add_argument("--enrich", type=int, metavar="N", nargs="?", const=0,
                   help="match saints to Wikidata (N at most; default all), then exit")
    p.add_argument("--stats", action="store_true", help="print directory statistics and exit")
    p.add_argument("--rebuild", action="store_true",
                   help="rebuild the directory from scratch (reuses downloaded data), then exit")
    p.add_argument("--reset", action="store_true", help="delete the local directory and caches, then exit")
    p.add_argument("--terminal", action="store_true",
                   help="show what saintd detects about this terminal (name, version, colours, graphics), then exit")
    args = p.parse_args(argv)

    if args.terminal:
        from . import term
        from .config import Config
        info = term.detect()
        print(term.report(info))
        setting = Config()["graphics"]
        mode = term.effective_mode(setting, info)
        print(f"\n  Pictures setting: {setting}  ->  {term.MODE_LABELS[mode]}")
        return 0

    if args.sync or args.rebuild or args.enrich is not None or args.stats or args.reset:
        from .core import Context
        from .net import Cancelled
        ctx = Context()
        ctx.http_bg.on_wait = _print_wait
        try:
            if args.reset:
                ctx.db.wipe()
                print("Local directory and caches deleted.")
                return 0
            if args.rebuild:
                ctx.db.wipe_directory()
            if args.sync or args.rebuild:
                ctx.syncer.build(_console_report())
                print()
            if args.enrich is not None:
                n = ctx.syncer.enrich(_console_report(), limit=args.enrich or None)
                print(f"\nProcessed {n} entries.")
            st = ctx.db.stats()
            print(f"\nDirectory: {st['people']} saints & groups ({st['total']} entries incl. feasts/icons), "
                  f"{st['lives']} with lives, {st['matched']} matched to Wikidata, {st['pending']} awaiting lookup.")
        except KeyboardInterrupt:
            ctx.http_bg.stop.set()
            print("\nStopped. Progress so far is saved; run again to continue.")
            return 130
        except Cancelled:
            print("\nStopped.")
            return 130
        finally:
            ctx.close()
        return 0

    from .app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
