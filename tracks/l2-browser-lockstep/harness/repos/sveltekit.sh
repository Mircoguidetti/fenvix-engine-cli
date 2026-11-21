# sveltejs/kit basics app, round 4 (lockstep): round 3's script, with every run starting from the same cache state.
# Vite's dependency cache (node_modules/.vite) is written by the first run of a series and read by the next ones; a
# fresh CI checkout starts without it every time. Since the trunk records file sizes the app server stats (R-055 V6),
# the first --det run after the plain runs differed from runs 2-10 in the app's own span log size (gate runs
# 44953971010, 44958432899: run 1 only, every variant). reset() now clears the cache before every run, plain and det.
# shellcheck source=/dev/null
source "$L2_H3/repos/sveltekit.sh"

r3_reset() { :; }
eval "$(declare -f reset | sed '1s/reset/r3_reset/')"

reset() {
  r3_reset
  (cd packages/kit/test/apps/basics && rm -rf node_modules/.vite node_modules/.vite-temp test/spans.jsonl)
}
