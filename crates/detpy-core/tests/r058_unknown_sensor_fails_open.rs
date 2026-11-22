//! R-058: `judge` has no list of sensors it understands, and `required_controls` fails OPEN.
//!
//! `required_controls` (provable.rs:917) ends:
//!
//!     } else {
//!         // a sensor the core does not know: clause 1 of `judge` has already refused it
//!         &[]
//!     }
//!
//! Clause 1 of `judge` has NOT refused it. Clause 1 checks only that the sensor string is non-empty
//! and that `contract` and `surface` match this core's. It never compares the NAME against anything:
//! grepping provable.rs shows the only places a sensor name is inspected are the two
//! `starts_with("py-")` / `starts_with("node-")` tests inside `required_controls` itself.
//!
//! So for any sensor name outside those two prefixes, clause 3 -- the clause whose whole job is to
//! refuse a run that had a `--det` control switched off -- iterates over an empty list and passes.
//! The comment asserting otherwise is the premise the fallback rests on, and it is false.
//!
//! This is reachable from the product: `node/src/session.js:327` (`provableField`) makes a
//! fully-cached Node run declare the sensor `cache-reuse/1` via `native.provableHeader(...)`, and
//! `provable_header` (crates/detpy-node/src/lib.rs:319) stamps this core's real `contract` and real
//! `surface_digest()` onto whatever name it is handed. `cache-reuse/1` starts with neither prefix.

use detpy_core::provable::{judge, surface_digest, Attestation, Verdict, SENSOR_CONTRACT};

fn attested(sensor: &str, controls: &[String]) -> Verdict {
    judge(&Attestation {
        sensor: Some(sensor),
        contract: Some(SENSOR_CONTRACT),
        surface: Some(&surface_digest()),
        runtime: Some("node24"),
        controls,
        unaccounted: &[],
        marks: &[],
        outside: &[],
    })
}

#[test]
fn the_cache_reuse_sensor_does_not_pass_with_every_control_switched_off() {
    // What a fully-cached Node run declares (node/src/session.js:341), with --det-disable having
    // switched off every control the accounting table's `Controlled` answers rest on.
    let v = attested("cache-reuse/1", &[]);
    assert_ne!(
        v,
        Verdict::Provable,
        "`cache-reuse/1` is a sensor this core has no rule for, and the run names no control at all; \
         clause 3 exists precisely to refuse this, but required_controls returned an empty list"
    );
}

#[test]
fn a_sensor_the_core_has_never_heard_of_is_not_provable() {
    // The general point: there is no allowlist. Any name at all gets a free pass through clause 3.
    for sensor in ["totally-made-up/9", "x", "py", "node", "deno-whatever/1"] {
        let v = attested(sensor, &[]);
        assert_ne!(
            v,
            Verdict::Provable,
            "sensor {sensor:?} is unknown to this core and declared no controls, yet judge returned \
             Provable; the default of this predicate is documented as NOT PROVEN"
        );
    }
}

#[test]
fn a_known_sensor_still_needs_its_controls() {
    // The control for comparison: the two known prefixes DO get checked, which is what makes the
    // fallback above a hole rather than a design.
    assert_ne!(attested("py-monitoring/1", &[]), Verdict::Provable);
    assert_ne!(attested("node-vitest/1", &[]), Verdict::Provable);
}
