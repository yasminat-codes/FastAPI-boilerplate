"""Canonical scheduler runtime placeholder."""


class SchedulerNotConfiguredError(RuntimeError):
    """Raised when the template scheduler entrypoint is invoked before scheduler support exists."""


def start_scheduler() -> None:
    """Placeholder runtime entrypoint for future scheduler support."""
    raise SchedulerNotConfiguredError(
        "The template scheduler runtime is not implemented yet. Add recurring job registration "
        "and scheduler wiring before invoking `src.app.scheduler:start_scheduler`."
    )


if __name__ == "__main__":
    start_scheduler()
