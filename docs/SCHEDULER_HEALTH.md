# Scheduler status across workers

Only one Gunicorn worker runs APScheduler. `/api/automations/health` reports a
local running scheduler or a current exclusive owner of the shared scheduler
lock. The latter returns `owned_by_another_worker`, with
`local_scheduler_running: false`. No process ID is returned. The exact next
evaluation time is returned only by the scheduler-owning worker.

On Linux the observer reads at most 1 MiB from `/proc/locks`, matching the lock
file's device and inode against an exclusive `FLOCK`. It does not read the
stored PID, create or modify files, acquire a probe lock, start a scheduler or
change any jobs. A stale PID file without a kernel lock is not active. Avoid
using a temporary probe lock: bootstrap could mistake it for a real owner.
The format comes from the [Linux proc_locks manual](https://man7.org/linux/man-pages/man5/proc_locks.5.html).

Missing ownership is distinguished from a disabled scheduler and one waiting
to start. Unsupported platforms, failed reads, oversized or unrecognized
kernel output, and a changed file identity report status unavailable. The UI
does not label these unknown checks as paused or online.

This is evidence of scheduler ownership, not proof that a specific job ran or
an email was delivered. It adds no scheduler failover, configuration changes,
provider calls or production notifications. Linux tests use a separate process
holding a temporary lock and confirm that its stale PID file is inactive after
exit. Tests outside Linux skip those process checks explicitly.
