//! Lockstep scheduler for Level 2 browser runs.
//!
//! One engine clock `T` (virtual nanoseconds since the run's epoch) and one event order for every component of
//! a browser end-to-end run: the Playwright runner (its timers and clock), the browser pages (CDP virtual time),
//! the app server processes (their timers and clock) and the database clock. No component moves in real time:
//! the shells (`node/src/pw/lockstep.js`) report when every component is quiet, and this scheduler decides what
//! happens next, in this order:
//!
//! 1. a pending message (an HTTP request of a page or of the runner, a WebSocket frame, a server push) is
//!    released: which one is a function of the pending set, the seed and the decision index only;
//! 2. otherwise the timers due at `T` fire;
//! 3. otherwise `T` advances to the next deadline any component reported, at most one quantum, and the pages
//!    get the same amount of virtual time.
//!
//! The seed space (round 4, "aimed at the flaking step") lives here too: with a seed, each decision may
//! (a) choose another message than the first in key order, (b) give the released message a latency (virtual
//! time that passes before the receiver sees it), (c) plan a socket fault for it (see [`Fault`]). Without a seed
//! every choice is index 0, latency is the base latency and there are no faults: one schedule, the default.
//! A seed perturbs only decisions inside the *focus* (a test, and optionally a window of decisions and a set of
//! message keys), so that exploration spends its seeds on the step that flakes.

use crate::order::{derive_seed, SplitMix64 as Rng};
use std::collections::{BTreeMap, HashMap};

/// What the shell must do next.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    /// Release message `id` (index `idx` of `n` eligible); deliver it after `latency_ns` of virtual time; apply
    /// `fault` on its connection.
    Release { id: u64, idx: u32, n: u32, latency_ns: u64, fault: Fault, decision: u64 },
    /// Advance the clock to `to_ns` (`budget_ns` of virtual time for the pages).
    Advance { to_ns: u64, budget_ns: u64 },
    /// Nothing to do: no message pending and nobody waits on time.
    Idle,
}

/// A socket fault planned for a released message (round 4, item 4). Applied by the shell's network layer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Fault {
    None,
    /// The connection is reset before the request reaches the server (the client sees ECONNRESET on write/read).
    ResetBeforeRequest,
    /// The server handles the request; the connection is reset before the response reaches the client.
    ResetBeforeResponse,
    /// The response is delivered in two parts with `delay_ns` of virtual time in between (a partial read).
    PartialResponse { delay_ns: u64 },
    /// The connection is closed by the server side right after the response (keep-alive reuse races).
    CloseAfterResponse,
}

impl Fault {
    pub fn name(&self) -> String {
        match self {
            Fault::None => "none".into(),
            Fault::ResetBeforeRequest => "reset-request".into(),
            Fault::ResetBeforeResponse => "reset-response".into(),
            Fault::PartialResponse { delay_ns } => format!("partial:{}", delay_ns / 1_000_000),
            Fault::CloseAfterResponse => "close-after".into(),
        }
    }
}

/// One pending message.
#[derive(Debug, Clone)]
pub struct Message {
    pub id: u64,
    /// Stable description (`kind method target body-digest`): the order key.
    pub key: String,
    /// Test the message belongs to (decision counters are per test).
    pub test: String,
    /// Messages of one connection keep their order: only the oldest pending one of a connection is eligible.
    pub conn: Option<u64>,
    /// Participant that holds it (worker index or server label).
    pub owner: String,
    /// Kind: `api`, `browser`, `ws-send`, `ws-recv`, `nav`.
    pub kind: String,
    seq: u64,
}

/// Seeded perturbations. Each list is a set of choices; a seed draws one per decision.
#[derive(Debug, Clone)]
pub struct SeedSpace {
    /// Latency choices in virtual nanoseconds (one is drawn per released message).
    pub latencies_ns: Vec<u64>,
    /// Fault choices (drawn per released message whose kind is in `fault_kinds`).
    pub faults: Vec<Fault>,
    /// Message kinds faults apply to (empty: none).
    pub fault_kinds: Vec<String>,
    /// Probability numerator over 1000 that a decision in focus draws a fault at all.
    pub fault_per_mille: u32,
    /// Reorder the eligible set (choose a seeded index instead of 0).
    pub reorder: bool,
}

impl Default for SeedSpace {
    fn default() -> Self {
        SeedSpace { latencies_ns: vec![], faults: vec![], fault_kinds: vec![], fault_per_mille: 0, reorder: true }
    }
}

/// Where a seed acts (round 4, item 2: "a seed space aimed at the flaking step").
#[derive(Debug, Clone, Default)]
pub struct Focus {
    /// Only decisions of tests whose id contains this text (empty: every test).
    pub test: String,
    /// Only decisions with index in `[from, to]` within the test (0 = unbounded).
    pub from: u64,
    pub to: u64,
    /// Only messages whose key contains one of these texts (empty: every message).
    pub keys: Vec<String>,
}

impl Focus {
    fn covers(&self, test: &str, decision: u64, key: &str) -> bool {
        if !self.test.is_empty() && !test.contains(&self.test) {
            return false;
        }
        if self.from > 0 && decision < self.from {
            return false;
        }
        if self.to > 0 && decision > self.to {
            return false;
        }
        self.keys.is_empty() || self.keys.iter().any(|k| key.contains(k.as_str()))
    }
}

/// The scheduler. One per run (one coordinator for every worker).
#[derive(Debug)]
pub struct Scheduler {
    seed: u64,
    seeded: bool,
    t_ns: u64,
    quantum_ns: u64,
    base_latency_ns: u64,
    pending: Vec<Message>,
    seq: u64,
    decisions: HashMap<String, u64>,
    /// Next deadline reported by each participant (absolute virtual ns); `None`: none.
    deadlines: BTreeMap<String, Option<u64>>,
    /// Participants that currently wait on time (a runner inside a Playwright call, a sleeping test, a server
    /// request blocked on a timer). Time advances only when at least one waits.
    waiting: BTreeMap<String, bool>,
    pub space: SeedSpace,
    pub focus: Focus,
    /// Every decision taken, in order (diagnosis; the shells record the per-test ones in the fingerprint).
    pub log: Vec<String>,
}

impl Scheduler {
    pub fn new(seed: u64, seeded: bool, start_ns: u64, quantum_ns: u64, base_latency_ns: u64) -> Self {
        Scheduler {
            seed,
            seeded,
            t_ns: start_ns,
            quantum_ns: quantum_ns.max(1),
            base_latency_ns,
            pending: Vec::new(),
            seq: 0,
            decisions: HashMap::new(),
            deadlines: BTreeMap::new(),
            waiting: BTreeMap::new(),
            space: SeedSpace::default(),
            focus: Focus::default(),
            log: Vec::new(),
        }
    }

    pub fn now(&self) -> u64 {
        self.t_ns
    }

    /// Move the clock forward (never backwards): a participant restored from a saved clock, or a release latency.
    pub fn advance_to(&mut self, t_ns: u64) {
        if t_ns > self.t_ns {
            self.t_ns = t_ns;
        }
    }

    pub fn set_deadline(&mut self, participant: &str, due_ns: Option<u64>) {
        self.deadlines.insert(participant.to_string(), due_ns);
    }

    pub fn set_waiting(&mut self, participant: &str, waiting: bool) {
        self.waiting.insert(participant.to_string(), waiting);
    }

    pub fn remove_participant(&mut self, participant: &str) {
        self.deadlines.remove(participant);
        self.waiting.remove(participant);
        self.pending.retain(|m| m.owner != participant);
    }

    pub fn enqueue(&mut self, id: u64, key: &str, test: &str, conn: Option<u64>, owner: &str, kind: &str) {
        self.seq += 1;
        self.pending.push(Message {
            id,
            key: key.to_string(),
            test: test.to_string(),
            conn,
            owner: owner.to_string(),
            kind: kind.to_string(),
            seq: self.seq,
        });
    }

    /// Drop a pending message (its request was aborted before release).
    pub fn cancel(&mut self, id: u64) -> bool {
        let n = self.pending.len();
        self.pending.retain(|m| m.id != id);
        n != self.pending.len()
    }

    pub fn pending_len(&self) -> usize {
        self.pending.len()
    }

    /// Earliest deadline over every participant, if any.
    pub fn next_deadline(&self) -> Option<u64> {
        self.deadlines.values().filter_map(|d| *d).min()
    }

    fn anyone_waiting(&self) -> bool {
        self.waiting.values().any(|w| *w)
    }

    fn draw(&self, test: &str, decision: u64, what: &str, n: usize) -> usize {
        if n <= 1 {
            return 0;
        }
        let mut r = Rng::new(derive_seed(self.seed, &format!("{test}\0{what}\0{decision}")));
        r.below(n as u64) as usize
    }

    /// Next action. Call only when every participant is quiet.
    pub fn next(&mut self) -> Action {
        if !self.pending.is_empty() {
            return self.release();
        }
        if !self.anyone_waiting() {
            return Action::Idle;
        }
        let cap = self.t_ns + self.quantum_ns;
        let to = match self.next_deadline() {
            Some(d) if d <= self.t_ns => self.t_ns, // due now: the shell fires it without advancing
            Some(d) => d.min(cap),
            None => cap,
        };
        let budget = to - self.t_ns;
        self.t_ns = to;
        Action::Advance { to_ns: to, budget_ns: budget }
    }

    fn release(&mut self) -> Action {
        // Eligible: the oldest pending message of each connection; messages without a connection always.
        let mut heads: HashMap<u64, u64> = HashMap::new();
        for m in &self.pending {
            if let Some(c) = m.conn {
                heads.entry(c).or_insert(m.seq);
            }
        }
        let mut eligible: Vec<&Message> =
            self.pending.iter().filter(|m| m.conn.map_or(true, |c| heads.get(&c) == Some(&m.seq))).collect();
        eligible.sort_by(|a, b| a.key.cmp(&b.key).then(a.seq.cmp(&b.seq)));
        let n = eligible.len();
        let test = eligible[0].test.clone();
        let d = {
            let e = self.decisions.entry(test.clone()).or_insert(0);
            *e += 1;
            *e
        };
        let in_focus = self.seeded && self.focus.covers(&test, d, &eligible[0].key);
        let idx = if in_focus && self.space.reorder { self.draw(&test, d, "net", n) } else { 0 };
        let chosen = eligible[idx].clone();
        let mut latency = self.base_latency_ns;
        let mut fault = Fault::None;
        if self.seeded && self.focus.covers(&chosen.test, d, &chosen.key) {
            if !self.space.latencies_ns.is_empty() {
                latency = self.space.latencies_ns[self.draw(&chosen.test, d, "lat", self.space.latencies_ns.len())];
            }
            if !self.space.faults.is_empty()
                && self.space.fault_kinds.iter().any(|k| k == &chosen.kind)
                && (self.draw(&chosen.test, d, "fault?", 1000) as u32) < self.space.fault_per_mille
            {
                fault = self.space.faults[self.draw(&chosen.test, d, "fault", self.space.faults.len())];
            }
        }
        self.pending.retain(|m| m.id != chosen.id);
        self.log.push(format!("{}\t{}\t{}/{}\t{}\t{}\t{}", chosen.test, d, idx, n, latency, fault.name(), chosen.key));
        Action::Release { id: chosen.id, idx: idx as u32, n: n as u32, latency_ns: latency, fault, decision: d }
    }
}

/// Parse a fault list (`reset-request,reset-response,partial:50,close-after`).
pub fn parse_faults(spec: &str) -> Vec<Fault> {
    spec.split(',')
        .filter_map(|s| {
            let s = s.trim();
            match s {
                "reset-request" => Some(Fault::ResetBeforeRequest),
                "reset-response" => Some(Fault::ResetBeforeResponse),
                "close-after" => Some(Fault::CloseAfterResponse),
                _ => s.strip_prefix("partial:").and_then(|ms| ms.parse::<u64>().ok()).map(|ms| Fault::PartialResponse {
                    delay_ns: ms * 1_000_000,
                }),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sched(seeded: bool) -> Scheduler {
        Scheduler::new(7, seeded, 0, 20_000_000, 1_000_000)
    }

    #[test]
    fn unseeded_releases_in_key_order_and_keeps_connection_order() {
        let mut s = sched(false);
        s.enqueue(1, "b", "t", Some(9), "w0", "ws-send");
        s.enqueue(2, "a", "t", Some(9), "w0", "ws-send");
        s.enqueue(3, "c", "t", None, "w0", "api");
        // Connection 9: only message 1 (oldest) is eligible although "a" sorts first.
        match s.next() {
            Action::Release { id, idx, n, .. } => assert_eq!((id, idx, n), (1, 0, 2)),
            a => panic!("{a:?}"),
        }
        match s.next() {
            Action::Release { id, .. } => assert_eq!(id, 2),
            a => panic!("{a:?}"),
        }
        match s.next() {
            Action::Release { id, .. } => assert_eq!(id, 3),
            a => panic!("{a:?}"),
        }
        assert_eq!(s.next(), Action::Idle);
    }

    #[test]
    fn advance_only_when_someone_waits_capped_at_quantum() {
        let mut s = sched(false);
        assert_eq!(s.next(), Action::Idle);
        s.set_waiting("w0", true);
        s.set_deadline("w0", Some(5_000_000));
        assert_eq!(s.next(), Action::Advance { to_ns: 5_000_000, budget_ns: 5_000_000 });
        s.set_deadline("w0", Some(500_000_000));
        assert_eq!(s.next(), Action::Advance { to_ns: 25_000_000, budget_ns: 20_000_000 });
        s.set_deadline("w0", None);
        assert_eq!(s.next(), Action::Advance { to_ns: 45_000_000, budget_ns: 20_000_000 });
    }

    #[test]
    fn same_seed_same_schedule() {
        let run = || {
            let mut s = sched(true);
            s.space.latencies_ns = vec![0, 5_000_000, 50_000_000];
            let mut out = vec![];
            for i in 0..6 {
                s.enqueue(i, &format!("k{}", 5 - i), "t", None, "w0", "browser");
            }
            while let Action::Release { id, latency_ns, .. } = s.next() {
                out.push((id, latency_ns));
            }
            out
        };
        assert_eq!(run(), run());
    }

    #[test]
    fn focus_limits_perturbation() {
        let mut s = sched(true);
        s.focus = Focus { test: "other".into(), ..Focus::default() };
        s.space.latencies_ns = vec![9];
        for i in 0..4 {
            s.enqueue(i, &format!("k{i}"), "t", None, "w0", "api");
        }
        // Not in focus: index 0 and base latency every time.
        for want in 0..4 {
            match s.next() {
                Action::Release { id, idx, latency_ns, .. } => assert_eq!((id, idx, latency_ns), (want, 0, 1_000_000)),
                a => panic!("{a:?}"),
            }
        }
    }

    #[test]
    fn faults_only_on_listed_kinds() {
        let mut s = sched(true);
        s.space.faults = parse_faults("reset-response,partial:40");
        s.space.fault_kinds = vec!["api".into()];
        s.space.fault_per_mille = 1000;
        s.enqueue(1, "a", "t", None, "w0", "browser");
        match s.next() {
            Action::Release { fault, .. } => assert_eq!(fault, Fault::None),
            a => panic!("{a:?}"),
        }
        s.enqueue(2, "b", "t", None, "w0", "api");
        match s.next() {
            Action::Release { fault, .. } => assert_ne!(fault, Fault::None),
            a => panic!("{a:?}"),
        }
        assert_eq!(parse_faults("partial:40")[0], Fault::PartialResponse { delay_ns: 40_000_000 });
    }
}
