# Lockstep headless shell (round 4, §5(1)(c))

Why (source read 2026-11-19, `chromium/src` main @ ab03983c, `third_party/blink/renderer/platform/scheduler`):
when the engine pauses a page's virtual time, Blink fences every task queue whose traits say
`can_run_when_virtual_time_paused = false` (`MainThreadSchedulerImpl::OnVirtualTimePaused`). Loading queues
(`FrameSchedulerImpl::LoadingTaskQueueTraits`: response headers, body chunks, load completion) keep the default
`true`, so a response the engine hands over during a pause is processed at a moment decided by the mojo data pipe in
real time: sometimes at once, sometimes in the next slice. That is the remaining divergence of the uptime-kuma setup
chain (INTERMEDIATE-1 §4.1, INTERMEDIATE-2).

Patch: `0001-lockstep-loading-follows-virtual-time.patch` adds the switch
`--lockstep-loading-follows-virtual-time`; with it the loading queues are fenced like timer queues while virtual time
is paused, so a page sees the network only inside a budget the engine grants. Without the switch nothing changes.

Build (not run: see INTERMEDIATE-2 "Blocked"): Chromium tag matching Playwright's headless shell (157.0.8103.78 for
chromium_headless_shell-1243), `gn gen out/Lockstep --args='is_debug=false is_component_build=false symbol_level=0
blink_symbol_level=0 enable_nacl=false use_remoteexec=false headless_use_embedded_resources=true'`,
`autoninja -C out/Lockstep headless_shell`, ship `out/Lockstep/headless_shell` + `*.pak`/`icudtl.dat`/`v8_context_snapshot.bin`
as `chrome-headless-shell` (the engine points `DETJS_PW_EXECUTABLE` at it and adds the switch).
Resources DECLARED by Chromium's Linux build docs: at least 100 GB of free disk, 8 GB RAM (16+ recommended), many CPU
hours (no remote execution for external builders). This container: 4 vCPU, 55 GB free, and
`chromium.googlesource.com` is not reachable (MEASURED). GitHub-hosted runners: 4 vCPU, ~14 GB disk, 6 h per job
(DECLARED, GitHub docs).
