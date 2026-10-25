"""Explicit simulator lifecycle control (ADR-015).

The simulator is opt-in: nothing here runs unless invoked (or the
``run_simulator`` service drives an active run). All state lives in
``simulator_*`` tables; ``reset`` only deletes those rows.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from simulator import engine
from simulator.engine import SimulatorError
from simulator.status import active_run


def _parse_gate(raw):
    """``ID:CLOSE_TICK[:OPEN_TICK]`` → gate spec dict."""
    parts = str(raw).split(":")
    if len(parts) not in (2, 3):
        raise CommandError(
            f"--gate expects ID:CLOSE_TICK[:OPEN_TICK], got {raw!r}"
        )
    try:
        crossing_id = int(parts[0])
        close_tick = int(parts[1])
        open_tick = int(parts[2]) if len(parts) == 3 else None
    except ValueError:
        raise CommandError(f"Invalid --gate value: {raw!r}") from None
    return {
        "crossing_id": crossing_id,
        "close_tick": close_tick,
        "open_tick": open_tick,
    }


class Command(BaseCommand):
    help = (
        "Control the traffic/crossing simulator: start, pause, resume, "
        "stop, tick (manual advance), status, reset. All state is "
        "simulation-scoped and labelled as demo data."
    )

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        p = sub.add_parser("start", help="Start a new run (fails if one is active).")
        p.add_argument("--label", default="")
        p.add_argument("--vehicles", type=int, default=None,
                       help=f"Static simulated users parked near crossings (default {settings.SIM_DEFAULT_VEHICLES}, max {settings.SIM_MAX_VEHICLES})")
        p.add_argument("--duration", type=int, default=None,
                       help="Scenario duration in seconds")
        p.add_argument("--tick", type=int, default=None,
                       help="Seconds per tick (default SIM_TICK_SECONDS)")
        p.add_argument("--seed", type=int, default=None,
                       help="Deterministic seed (default: random)")
        p.add_argument("--gate", action="append", default=[], metavar="ID:CLOSE[:OPEN]",
                       help="Physically close crossing ID at CLOSE tick (parked users count as "
                            "waiting), reopen at OPEN tick. Repeatable. The status only surfaces "
                            "after a prompt is confirmed.")
        p.add_argument("--random-gates", type=int, default=0,
                       help="Also close N random crossings")
        p.add_argument("--close-tick", type=int, default=3,
                       help="Tick at which random gates close")
        p.add_argument("--open-tick", type=int, default=30,
                       help="Tick at which random gates reopen")
        p.add_argument("--auto-confirm", action="store_true",
                       help="Auto-confirm every raised gate prompt (no web-app click needed)")
        p.add_argument("--force", action="store_true",
                       help="Stop the active run first")

        sub.add_parser("pause", help="Pause the active run")
        sub.add_parser("resume", help="Resume a paused run")
        sub.add_parser("stop", help="Stop the active run (gates revert)")
        sub.add_parser("status", help="Show the active/latest run")

        t = sub.add_parser("tick", help="Advance the active run manually")
        t.add_argument("--n", type=int, default=1, help="Number of ticks")

        sub.add_parser("reset", help="Delete ALL simulator data (refuses while active)")

    def handle(self, *args, **options):
        action = options["action"]
        handler = getattr(self, f"do_{action}")
        handler(options)

    def do_start(self, options):
        gates = [_parse_gate(raw) for raw in options["gate"]]
        gates += engine.build_gate_specs(
            [],
            options["random_gates"],
            options["close_tick"],
            options["open_tick"],
        )
        try:
            run = engine.start_run(
                label=options["label"],
                vehicles=options["vehicles"],
                duration_seconds=options["duration"],
                seed=options["seed"],
                tick_seconds=options["tick"],
                gates=gates,
                auto_confirm=options["auto_confirm"],
                force=options["force"],
            )
        except SimulatorError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Started run #{run.pk} ({run.label}): "
                f"{run.vehicle_count} static simulated users, "
                f"{run.duration_seconds}s at {run.tick_seconds}s/tick, "
                f"seed {run.seed}, "
                f"{len(run.config.get('gates') or [])} gate event(s)."
            )
        )
        if not run.config.get("gates"):
            self.stdout.write(
                "No gate events configured — gates stay open. Use "
                "--gate ID:CLOSE:OPEN or --random-gates N for closures."
            )
        elif run.config.get("auto_confirm"):
            self.stdout.write(
                "Prompts auto-confirm: simulated gate status appears "
                "without a web-app click."
            )
        else:
            self.stdout.write(
                "Confirm prompts in the web app (violet card on the map) "
                "to mark a gate simulated-closed, or re-run with "
                "--auto-confirm."
            )
        self.stdout.write(
            "Drive it with the simulator service (docker compose "
            "--profile simulation up) or `manage.py simulator tick`."
        )

    def do_pause(self, options):
        run = self._active_or_error()
        engine.pause_run(run)
        self.stdout.write(self.style.SUCCESS(f"Paused run #{run.pk}."))

    def do_resume(self, options):
        run = self._active_or_error()
        engine.resume_run(run)
        self.stdout.write(self.style.SUCCESS(f"Resumed run #{run.pk}."))

    def do_stop(self, options):
        run = self._active_or_error()
        engine.stop_run(run)
        self.stdout.write(
            self.style.SUCCESS(
                f"Stopped run #{run.pk}; simulated gates reverted."
            )
        )

    def do_status(self, options):
        run = active_run()
        if run is None:
            from simulator.models import SimulationRun

            run = SimulationRun.objects.first()
            if run is None:
                self.stdout.write("No simulation runs exist.")
                return
        data = {
            "id": run.pk,
            "label": run.label,
            "status": run.status,
            "seed": run.seed,
            "ticks": run.ticks,
            "config": run.config,
            "started_at": run.started_at.isoformat(),
            "finished_at": (
                run.finished_at.isoformat() if run.finished_at else None
            ),
            "heartbeat_at": run.heartbeat_at.isoformat(),
            "error": run.error,
        }
        self.stdout.write(json.dumps(data, indent=2))

    def do_tick(self, options):
        run = self._active_or_error()
        if run.status != run.STATUS_RUNNING:
            raise CommandError(
                f"Run #{run.pk} is {run.status}; resume it before ticking."
            )
        n = options["n"]
        if n <= 0:
            raise CommandError("--n must be positive")
        for _ in range(n):
            summary = engine.tick_run(run)
            if summary is None:
                break
            self.stdout.write(
                f"tick {summary['tick']}: {summary['vehicles']} users, "
                f"gate changes {summary['gate_changes'] or '[]'}"
                + (" — finished" if summary["finished"] else "")
            )
            run.refresh_from_db(fields=["status", "ticks"])
            if summary["finished"]:
                break

    def do_reset(self, options):
        try:
            result = engine.reset_simulation()
        except SimulatorError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Reset complete: deleted {result['deleted']} "
                "simulator-owned row(s): "
                + json.dumps(result["by_model"], sort_keys=True)
            )
        )

    def _active_or_error(self):
        run = active_run()
        if run is None:
            raise CommandError(
                "No simulation run is active. Start one with "
                "`manage.py simulator start`."
            )
        return run
