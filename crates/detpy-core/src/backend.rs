//! Interception backends.
//!
//! The core does not care *how* events are captured. A backend turns the
//! interactions of the code under test with the outside world into
//! [`Event`]s and pushes them into an [`EventSink`] (the [`Recorder`]).
//!
//! * [`Backend::PythonHooks`] (implemented): the pytest plugin monkeypatches
//!   Python-level APIs (`time`, `random`, `os.listdir`, `socket`, ...). It sees
//!   only what goes through those Python entry points.
//! * [`Backend::Syscall`] (reserved): a Hermit-style tracer (ptrace/seccomp)
//!   that runs the interpreter under a deterministic scheduler and intercepts
//!   `clock_gettime`, `getrandom`, `getdents64`, `connect`, ... at the syscall
//!   boundary. It would report [`Source::Syscall`] (or the more specific
//!   source) events into the same sink and fingerprint format, so traces,
//!   verifier and cache keep working unchanged. Capabilities tell the
//!   verifier/harness which classes of divergence a backend can explain.
//!
//! [`Recorder`]: crate::recorder::Recorder
//! [`Source::Syscall`]: crate::event::Source::Syscall

use crate::event::Event;
use serde::{Deserialize, Serialize};

pub trait EventSink {
    fn record(&mut self, event: Event);
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Backend {
    PythonHooks,
    Syscall,
}

/// What a backend controls (makes deterministic) and what it only observes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Capabilities {
    pub controls_time: bool,
    pub controls_random: bool,
    pub controls_fs_order: bool,
    pub controls_network: bool,
    pub controls_entropy: bool,
    pub controls_scheduling: bool,
    pub sees_native_code: bool,
    pub sees_subprocesses: bool,
}

impl Backend {
    pub fn name(self) -> &'static str {
        match self {
            Backend::PythonHooks => "python-hooks",
            Backend::Syscall => "syscall",
        }
    }

    pub fn implemented(self) -> bool {
        matches!(self, Backend::PythonHooks)
    }

    pub fn capabilities(self) -> Capabilities {
        match self {
            Backend::PythonHooks => Capabilities {
                controls_time: true,
                controls_random: true,
                controls_fs_order: true,
                controls_network: true,
                controls_entropy: false,
                controls_scheduling: false,
                sees_native_code: false,
                sees_subprocesses: false,
            },
            Backend::Syscall => Capabilities {
                controls_time: true,
                controls_random: true,
                controls_fs_order: true,
                controls_network: true,
                controls_entropy: true,
                controls_scheduling: true,
                sees_native_code: true,
                sees_subprocesses: true,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_python_hooks_is_implemented() {
        assert!(Backend::PythonHooks.implemented());
        assert!(!Backend::Syscall.implemented());
        assert!(!Backend::PythonHooks.capabilities().controls_scheduling);
        assert!(Backend::Syscall.capabilities().sees_native_code);
    }
}
