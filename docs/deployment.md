# Shared GPU deployment

The live MotionBricks backend needs GPU access, but does not need a dedicated
GPU allocation. The browser viewer and recorded videos can run independently.

Use an **existing shared SkyPilot cluster** with MotionBricks, its separately
obtained assets, the installed director and its Python environment already set
up. Configure Gemini credentials in that runtime's `.env` as in the installation
instructions. The task does not download assets, fetch secrets or provision
infrastructure.

From this director repository, submit the tracked foreground process:

```sh
sky exec existing-shared-cluster deploy/skypilot-shared.yaml \
  --env MOTIONBRICKS_CHECKOUT=/absolute/path/to/MotionBricks \
  --detach-run
```

The supplied task requests `A6000:0.25`, leaving the remaining logical GPU
capacity available to other SkyPilot jobs on that same cluster. Override with
`--gpus GPU_TYPE:FRACTION` for the existing hardware and an appropriate measured
share. The quarter-GPU request is a starting scheduling value, not a benchmark,
a hard compute/memory limit or a promise of four simultaneous demos. Measure
active inference latency and memory while sharing before choosing production
capacity. Other jobs must also be submitted with resource requests that allow
sharing.

Use `sky exec`, not `sky launch` or `sky jobs launch`, for this task: those launch
commands can provision a separate full-GPU instance or GPU-reserving pod even
when the job requests a fraction. Likewise, fractional jobs in different pods
cannot share a normally exclusive Kubernetes GPU allocation. Independent pods
require GPU sharing configured by the infrastructure operator, or jobs must run
in the same existing cluster. Changing a job fraction does not itself lower the
bill for the underlying machine.

The process remains attached to its SkyPilot job, so `sky queue` shows it as
running until it exits. Do not background the backend or launch it over SSH
outside the scheduler; that makes resource accounting and idle detection wrong.
The service binds to loopback by default. Forward its port privately through
SSH/Tailscale; the task opens no public ports. If another backend uses port6090
in the same cluster, override `MOTIONBRICKS_PORT` with a free port.

To stop only the demo and return its job resources:

```sh
sky cancel existing-shared-cluster JOB_ID --yes
```

Leave shared infrastructure running for its other users. If a separate cluster
was created solely for the demo, release that allocation with
`sky down dedicated-demo-cluster --yes` after copying anything needed from its
ephemeral storage. On an SSH node pool this releases the demo's allocation; it
does not power off the underlying shared host. Video hosting should stay on a
separate CPU/static host so it remains available while the simulation is off.

See [SkyPilot cluster jobs](https://docs.skypilot.co/en/stable/reference/job-queue.html)
for fractional scheduling and [CLI semantics](https://docs.skypilot.co/en/latest/reference/cli.html)
for cluster execution and teardown.
