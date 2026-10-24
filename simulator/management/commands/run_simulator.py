"""The simulator service loop (the Compose ``simulator`` service).

Waits for an active run (``manage.py simulator start``), then drives it:
one coarse tick per ``tick_seconds`` while ``running``. A stopped /
finished run ends the drive and the loop goes back to waiting — the
main app never depends on this process.
"""
import time

from django.core.management.base import BaseCommand, CommandError

from simulator import engine
from simulator.status import active_run


class Command(BaseCommand):
    help = "Drive the active simulation run (simulator service)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=None,
            help="Override wall-clock seconds between ticks "
            "(default: the run's tick_seconds).",
        )
        parser.add_argument(
            "--idle-wait",
            type=float,
            default=2.0,
            help="Seconds between polls when no run is active.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        idle_wait = max(0.5, options["idle_wait"])
        engine.install_sigterm_handler()
        interrupted = engine.interrupt_stale_runs()
        if interrupted:
            self.stdout.write(
                f"Marked {interrupted} stale run(s) stopped "
                "(heartbeat lost)."
            )
        self.stdout.write(
            "Simulator service running — waiting for an active run "
            "(manage.py simulator start …)."
        )
        try:
            while True:
                run = active_run()
                if run is None:
                    time.sleep(idle_wait)
                    continue
                self.stdout.write(
                    f"Driving run #{run.pk} ({run.label}): "
                    f"{run.vehicle_count} vehicles, "
                    f"{run.duration_seconds}s at {run.tick_seconds}s/tick."
                )
                try:
                    status = engine.drive_run(run, interval=interval)
                except Exception as exc:
                    run.refresh_from_db()
                    engine.fail_run(run, note=f"service error: {exc}")
                    raise CommandError(
                        f"Run #{run.pk} failed: {exc}"
                    ) from exc
                self.stdout.write(
                    f"Run #{run.pk} is now {status}; waiting for the "
                    "next run."
                )
        except (KeyboardInterrupt, SystemExit):
            run = active_run()
            if run is not None:
                engine.stop_run(run, note="simulator service stopped")
                self.stdout.write(
                    f"Stopped run #{run.pk} on shutdown."
                )
            self.stdout.write("Simulator service stopped.")
