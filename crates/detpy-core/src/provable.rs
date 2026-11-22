//! The general rule: a test is IDENTICAL only when everything it did is accounted for.
//!
//! Founder decision, 2026-11-21: *"Never a green on a doubt. If the engine is not certain, it answers NOT PROVEN
//! and the test is rerun. A test reported green that was red is the worst damage we can do to a customer. Speed
//! never buys an exception."*
//!
//! Until this module existed the verdict was decided the other way round: the verifier reported IDENTICAL whenever
//! it had seen no difference, and only an explicit `uncontrolled.*` mark pulled it back. That is a blacklist over
//! the channels somebody had thought of, so every channel nobody had thought of was a silent green. Reviews R-051,
//! R-054, R-055 and R-057 each found new instances of it; channel number 27 would have been a lie too.
//!
//! This module inverts the default. One table, one predicate, one place:
//!
//! * [`account`] classifies a single callable crossing the Python/JS → C boundary. Four of the five answers are
//!   "accounted for"; the fifth, [`Accounting::Unaccounted`], is what every name the table does not list gets.
//! * [`judge`] is the only predicate that may conclude that a test is provable. [`verify`](crate::verify) and the
//!   cache both call it, so the cache and the verifier cannot drift apart.
//!
//! # Why this is a closed world and the old list was not
//!
//! Default-deny is only worth something if the set being denied is bounded. It is, and that is the whole argument:
//!
//! 1. A test can only obtain outside information by calling into C — either a callable of the interpreter and its
//!    standard library, or one of an extension module.
//! 2. *Which* callables exist in the interpreter and its standard library is fixed by the `runtime` run input
//!    (interpreter, version, platform, machine), which the verifier already compares. The surface is finite and
//!    auditable, and it cannot change under us without `runtime` changing with it.
//! 3. So the table carries [`AUDITED_RUNTIMES`]: the interpreter versions its claims were actually audited
//!    against. A run on any other version is NOT PROVEN before a single callable is looked at. A callable that did
//!    not exist when this table was written therefore cannot be reached while the verdict is still IDENTICAL.
//! 4. The extension modules are pinned by content, not by name: `inputs.deps` digests the bytes of the installed
//!    packages, so a different extension makes every test of the run diverge. What is left — an extension whose own
//!    C code reads outside state while its bytes stay the same — is the declared residual below.
//!
//! The old list was a claim about channels in the world, which is unbounded. This one is a claim about named
//! callables in a pinned interpreter, which is not.
//!
//! # The declared residual
//!
//! An in-process sensor cannot see a call made from C to C: an extension module that opens a file or reads the
//! clock inside its own C code emits no Python-level call and no audit event. Two things narrow it, and what is
//! left is stated rather than hidden:
//!
//! * a changed extension changes `inputs.deps`, so it cannot pass as identical;
//! * a test that loads a native extension which is not on the shell's declared controlled list is NOT PROVEN
//!   (`uncontrolled.native:<module>`).
//!
//! Truly residual: a *listed* extension reading the real clock through the vDSO. No in-process sensor sees it, and
//! neither does strace — the parallel measurement session MEASURED 600,000 real clock reads producing 0 syscalls.
//! It is a declared product limit (docs/LIMITS.md C2f, K1), not something this module pretends to cover.

use crate::fingerprint::{digest_bytes, TestRecord};
use serde::{Deserialize, Serialize};

/// Version of the contract between a shell's sensor and this table.
///
/// A shell writes it into the trace header (`meta.provable.contract`). A trace that declares a different number,
/// or none at all, is NOT PROVEN for every test: the core will not guess what an unknown sensor did or did not
/// look at. Bump this whenever the meaning of what a shell must report changes.
pub const SENSOR_CONTRACT: u32 = 1;

/// Interpreter and runtime versions the claims in this table were audited against.
///
/// A run whose `runtime` input names anything else is NOT PROVEN (point 3 of the module argument). `python3.12` is
/// the product floor (3.11 is refused by the installer), and `sys.monitoring` — the Python sensor — exists from
/// 3.12, so there is no supported Python without a sensor.
pub const AUDITED_RUNTIMES: &[&str] = &["cpython3.12", "cpython3.13", "cpython3.14", "node22", "node24", "node26"];

/// What the engine can say about one callable.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Accounting {
    /// A pure function of its arguments: it carries no information from outside the process. Calling it twice with
    /// the same arguments in two runs cannot make the runs differ.
    Pure,
    /// `--det` gives every run the same value (the virtual clock, the seeded generators, the pinned host name, the
    /// pinned process id, controlled entropy).
    Controlled,
    /// Every call produces an event whose value carries what the test saw (`fs.read`, `fs.stat`, `net.connect`,
    /// `env.get`, ...), so a different value is a different fingerprint.
    Recorded,
    /// What it returns is pinned by a run input the verifier compares (`runtime`, `code`, `deps`, `env:NAME`).
    Input,
    /// Everything else, including every name this table does not list. The test is NOT PROVEN.
    Unaccounted,
}

impl Accounting {
    /// True for the four answers that let a test still be reported identical.
    pub fn is_accounted(self) -> bool {
        self != Accounting::Unaccounted
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Accounting::Pure => "pure",
            Accounting::Controlled => "controlled",
            Accounting::Recorded => "recorded",
            Accounting::Input => "input",
            Accounting::Unaccounted => "unaccounted",
        }
    }
}

/// How a whole module is treated before any single name is looked at.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ModulePolicy {
    /// Every callable of the module is a pure function of its arguments, except the names [`account`] lists.
    Pure,
    /// The engine's own machinery and the test runner's: controlled by the `runner` and `runtime` inputs
    /// (Rule E of the PROVABLE measurement).
    Infra,
    /// The module reaches outside state: every callable must be named, and anything unnamed is unaccounted.
    Enumerated,
    /// Nothing is claimed about this module. Reaching it at all is NOT PROVEN.
    Unknown,
}

/// Modules whose whole callable surface is a pure function of its arguments.
///
/// These are the C accelerators of the standard library: text, numbers, containers, codecs, hashing, compression,
/// serialisation of values already in the process. None of them opens a file, reads a clock, or asks the operating
/// system anything. A pure-Python function needs no entry of its own: it can only reach outside state through one
/// of the callables listed here or in the enumerated modules below, and that call is seen too.
const PURE_MODULES: &[&str] = &[
    "_abc",
    "_ast",
    "_bisect",
    "_blake2",
    "_bz2",
    "_codecs",
    "_codecs_cn",
    "_codecs_hk",
    "_codecs_iso2022",
    "_codecs_jp",
    "_codecs_kr",
    "_codecs_tw",
    "_collections",
    "_contextvars",
    "_csv",
    "_datetime",
    "_decimal",
    "_elementtree",
    "_functools",
    "_hashlib",
    "_heapq",
    "_json",
    "_lsprof",
    "_lzma",
    "_md5",
    "_multibytecodec",
    "_opcode",
    "_operator",
    "_pickle",
    "_queue",
    "_sha1",
    "_sha2",
    "_sha3",
    "_sre",
    "_stat",
    "_statistics",
    "_string",
    "_struct",
    "_symtable",
    "_typing",
    "_weakref",
    "_weakrefset",
    "_zoneinfo",
    "array",
    "binascii",
    "bisect",
    "cmath",
    "datetime",
    "errno",
    "itertools",
    "math",
    "pyexpat",
    "unicodedata",
    "zlib",
];

/// The engine's own code and the test runner's: the declared controlled set (Rule E).
///
/// The reasoning is the one the PROVABLE measurement wrote down: the engine pins the interpreter and the runner
/// identity as run inputs, precompiles the standard library under the fixed hash seed, pins the time zone and the
/// locale, and nothing writes that environment during a run. A call the runner makes for its own bookkeeping is
/// not something the test observed.
const INFRA_PREFIXES: &[&str] = &[
    "detpy", "_pytest", "pytest", "pluggy", "iniconfig", "_distutils_hack", "exceptiongroup", "detjs",
];

/// Native extension modules whose own C code the engine has reasoned about, **by name**.
///
/// This list is only for extensions that are not already covered by where they live. The shells decide the rest
/// by path, which is what makes the rule portable: the interpreter's own extension modules are part of the
/// interpreter and pinned by the `runtime` input, and the engine's and the runner's are the declared controlled
/// set (Rule E). Which standard-library modules are separate shared objects at all depends on how the
/// interpreter was built -- MEASURED: `_asyncio` and thirteen others are separate `.so` files on the hosted
/// CPython 3.13 that CI uses and built into the binary in the development container -- so a list of names is the
/// wrong instrument for them.
///
/// A test that loads an extension covered by neither is NOT PROVEN: its C code could read a file or the real
/// clock without emitting anything a sensor can see (the declared residual).
pub const CONTROLLED_NATIVE: &[&str] = &[
    // the engine's own extension and the accelerators of the pure modules above
    "detpy._core",
    // `time-machine`'s extension, which the ENGINE itself imports: `python/detpy/clock.py` reads an active
    // travel through `clock_time_machine_ns` so that a travel is honoured under `--det` instead of being
    // ignored, and while a travel is active the virtual clock returns its destination (a ticking travel
    // advances with the VIRTUAL counter). So the load is the engine's own act (Rule E) and what the extension
    // answers is pinned by the engine's control, which tests/test_clock.py::test_time_machine_travel_is_honoured
    // asserts. Without this entry, merely HAVING time-machine installed made every test of every suite NOT
    // PROVEN -- MEASURED on this branch, a one-test project in a venv with time-machine:
    // `unaccounted` = ["native:_time_machine"], and the engine, not the test, is what imported it.
    // Measured as well, and honestly incomplete: travelling and reading `time`, `monotonic` and `localtime`
    // inside the travel, then `time` after it, made ZERO syscalls under `strace` -- which does not prove it
    // never reads the real clock, because a clock read goes through the vDSO and never appears in a trace.
    // What the claim rests on is the engine's control over what it returns, not on that measurement.
    "_time_machine",
    "_abc",
    "_bisect",
    "_blake2",
    "_bz2",
    "_codecs",
    "_collections",
    "_contextvars",
    "_csv",
    "_datetime",
    "_decimal",
    "_elementtree",
    "_functools",
    "_hashlib",
    "_heapq",
    "_json",
    "_lzma",
    "_md5",
    "_opcode",
    "_operator",
    "_pickle",
    "_queue",
    "_sha1",
    "_sha2",
    "_sha3",
    "_sre",
    "_statistics",
    "_struct",
    "_typing",
    "_zoneinfo",
    "array",
    "binascii",
    "cmath",
    "math",
    "pyexpat",
    "unicodedata",
    "zlib",
];

/// Classify one callable, named as the shell's sensor sees it: the defining module and the qualified name.
///
/// This is the only table. Anything it does not list is [`Accounting::Unaccounted`], which is what makes a channel
/// nobody has thought of land in NOT PROVEN instead of in IDENTICAL.
pub fn account(module: &str, qualname: &str) -> Accounting {
    if module.is_empty() {
        // a callable with no module: a lambda, a C function of an unknown extension, a bound method of an
        // anonymous type. Nothing is claimed about it.
        return Accounting::Unaccounted;
    }
    let top = module.split('.').next().unwrap_or(module);
    match module_policy(module, top) {
        ModulePolicy::Infra => return Accounting::Controlled,
        ModulePolicy::Pure => return pure_module_exception(top, qualname),
        ModulePolicy::Unknown => return Accounting::Unaccounted,
        ModulePolicy::Enumerated => {}
    }
    // The last component is what identifies the operation: `stat`, `socket.connect`, `Random.random`.
    let name = qualname.rsplit('.').next().unwrap_or(qualname);
    match top {
        "builtins" => builtins_account(qualname, name),
        "posix" | "os" | "nt" => posix_account(qualname, name),
        "time" => time_account(name),
        "_io" | "io" => io_account(name),
        "_socket" | "socket" => socket_account(name),
        "_thread" | "threading" => thread_account(name),
        "_random" | "random" => random_account(name),
        "select" | "_selectors" | "selectors" => select_account(qualname, name),
        "_sqlite3" | "sqlite3" => sqlite_account(name),
        "sys" => sys_account(name),
        "gc" => gc_account(name),
        "resource" => resource_account(name),
        "_imp" | "_frozen_importlib" | "_frozen_importlib_external" | "importlib" | "marshal" | "zipimport" => {
            import_account(name)
        }
        "_warnings" | "atexit" | "_tracemalloc" | "faulthandler" => Accounting::Pure,
        "_asyncio" => asyncio_account(name),
        "_interpreters" | "_interpqueues" | "_interpchannels" => subinterpreter_account(name),
        // the locale is pinned by `--det-locale` and is a run input the verifier compares, so what these answer
        // is the same in every run of a comparison
        "_locale" | "locale" => Accounting::Input,
        // the C tokenizer and the AST builder read source text they are handed, nothing else
        "_tokenize" => Accounting::Pure,
        "_ssl" => ssl_account(name),
        // `_posixsubprocess.fork_exec` is how `subprocess` starts a child, which the engine follows (see the
        // posix arm above); everything else of that module is not named, so it stays refused.
        "_posixsubprocess" => {
            if name == "fork_exec" {
                Accounting::Recorded
            } else {
                Accounting::Unaccounted
            }
        }
        "fcntl" | "termios" | "mmap" | "signal" | "_multiprocessing" | "_curses" | "pwd"
        | "grp" | "spwd" | "crypt" | "syslog" | "_uuid" | "_scproxy" | "msvcrt" | "winreg" | "nis" => {
            // every one of these reads state of the machine, the user database or another process, and none of
            // them has an event today. Named here so the report can say which, rather than "unknown module".
            Accounting::Unaccounted
        }
        _ => Accounting::Unaccounted,
    }
}

fn module_policy(module: &str, top: &str) -> ModulePolicy {
    if INFRA_PREFIXES.iter().any(|p| module == *p || module.starts_with(&format!("{p}."))) {
        return ModulePolicy::Infra;
    }
    if PURE_MODULES.contains(&top) {
        return ModulePolicy::Pure;
    }
    const ENUMERATED: &[&str] = &[
        "builtins", "posix", "os", "nt", "time", "_io", "io", "_socket", "socket", "_thread", "threading",
        "_random", "random", "select", "_selectors", "selectors", "_sqlite3", "sqlite3", "sys", "gc", "resource",
        "_imp", "_frozen_importlib", "_frozen_importlib_external", "importlib", "marshal", "zipimport",
        "_asyncio", "_interpreters", "_interpqueues", "_interpchannels",
        "_warnings", "atexit", "_tracemalloc", "faulthandler", "_tokenize", "_locale", "locale", "_ssl", "fcntl",
        "termios", "mmap", "signal",
        "_posixsubprocess", "_multiprocessing", "_curses", "pwd", "grp", "spwd", "crypt", "syslog", "_uuid",
        "_scproxy", "msvcrt", "winreg", "nis",
    ];
    if ENUMERATED.contains(&top) {
        return ModulePolicy::Enumerated;
    }
    ModulePolicy::Unknown
}

/// The names of an otherwise pure module that are not pure after all.
fn pure_module_exception(top: &str, qualname: &str) -> Accounting {
    let name = qualname.rsplit('.').next().unwrap_or(qualname);
    match (top, name) {
        // the clock of the C date module reads the real time of day
        ("datetime" | "_datetime", "now" | "today" | "utcnow" | "fromtimestamp" | "utcfromtimestamp") => {
            Accounting::Controlled
        }
        // reads the zoneinfo database from disk; the time zone is a run input and the data is pinned with it
        ("_zoneinfo", "ZoneInfo" | "__init__" | "clear_cache" | "from_file" | "no_cache") => Accounting::Input,
        _ => Accounting::Pure,
    }
}

/// `builtins`: pure, except for the names that reach outside the process.
///
/// The default is Pure here, and that is a closed-world claim over a surface the `runtime` input pins (point 2 of
/// the module argument), not a blacklist over channels. Every builtin is a container, text, number or object
/// operation except the ones below.
fn builtins_account(qualname: &str, name: &str) -> Accounting {
    match name {
        // opening a file is an `fs.read` / `fs.stat` event with the path and the digest of the bytes
        "open" => Accounting::Recorded,
        // the import system: the project's own source is `inputs.code`, everything else `inputs.deps`
        "__import__" => Accounting::Input,
        // identity and hashing expose the memory layout and the string hash seed; `--det` pins both (ASLR off,
        // a fixed PYTHONHASHSEED through the re-exec)
        "id" | "hash" => Accounting::Controlled,
        // reads the standard input, which no event carries; `breakpoint` enters the debugger, which also does
        "input" | "breakpoint" => Accounting::Unaccounted,
        // `vars`, `dir`, `globals`, `locals`, `compile`, `exec`, `eval`, `print`, `repr`, and every container,
        // text and number operation: a function of what is already in the process
        _ => {
            // a method of a C type reached through builtins (`builtins.list.append`, `builtins.str.encode`)
            let _ = qualname;
            Accounting::Pure
        }
    }
}

/// The C accelerator of `asyncio`.
///
/// What makes an async test unprovable is the ORDER in which the loop runs its callbacks, and that order is
/// Level 1 work which is not on this trunk. So every task, future, handle and loop operation stays
/// `Unaccounted` and an async test is NOT PROVEN, which is the honest answer today.
///
/// Two names are not that. `current_task` and the running-loop accessors only REPORT what this process is
/// already doing: outside a loop they answer `None` in every run, and inside one the test has already called
/// something refused above, so nothing is opened by naming them. They are named because the standard library
/// calls them on ordinary, entirely synchronous tests: since 3.12 every `logging` record carries `taskName`,
/// which calls `asyncio.current_task()`.
/// MEASURED (this branch, 37 ordinary tests under `--det`): before, a test whose only act was
/// `logging.getLogger(...).warning(...)` was NOT PROVEN with "not accounted for: api:_asyncio.current_task";
/// after, it is covered by Level 0, and the test that calls `asyncio.run` is still NOT PROVEN.
fn asyncio_account(name: &str) -> Accounting {
    match name {
        "current_task" | "_get_running_loop" | "_set_running_loop" | "get_running_loop" | "get_event_loop" => {
            Accounting::Pure
        }
        // tasks, futures, callback handles, the event loop itself: scheduling, which nothing here controls
        _ => Accounting::Unaccounted,
    }
}

/// Subinterpreters and the queues and channels between them (3.13+: `_interpreters`, `_interpqueues`,
/// `_interpchannels`).
///
/// Data crossing from another interpreter is as uncontrolled as data crossing from a child process, so every
/// operation stays `Unaccounted`. Registering the Python type objects with the C module is not an operation on
/// the channel: it hands the module types it is given, reads nothing and returns nothing, and the standard
/// library does it on import.
/// MEASURED (CI 44964230574, job `install (Debian, CPython 3.14, Node 26)`): on CPython 3.14 the install leg's
/// check `py_det_traces_identical` failed with "not accounted for: api:_interpqueues._register_heap_types",
/// so on 3.14 every test of an ordinary project came out NOT PROVEN.
fn subinterpreter_account(name: &str) -> Accounting {
    match name {
        "_register_heap_types" | "_register_queue_type" | "_register_channel_type" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

/// The methods of a C type, named `Type.method` by the sensor.
///
/// `account` compares the last component of a qualified name, which is what identifies an operation
/// (`stat`, `connect`, `random`). A method of a type needs the last TWO: `is_dir` on its own says nothing,
/// `DirEntry.is_dir` says the entry a recorded `scandir` handed out. Returns `None` when the name is not one
/// of them, so the caller falls through to its own table.
fn type_method_account(qualname: &str) -> Option<Accounting> {
    let mut parts = qualname.rsplitn(3, '.');
    let last = parts.next()?;
    let owner = parts.next()?;
    match (owner, last) {
        // the entries `scandir` hands out: part of the recorded enumeration, and their metadata is `fs.stat`
        (
            "DirEntry",
            "is_dir" | "is_file" | "is_symlink" | "is_junction" | "stat" | "inode" | "__fspath__" | "__init__",
        ) => Some(Accounting::Recorded),
        ("ScandirIterator", "__next__" | "__iter__" | "close" | "__enter__" | "__exit__") => {
            Some(Accounting::Recorded)
        }
        _ => None,
    }
}

fn posix_account(qualname: &str, name: &str) -> Accounting {
    // The sensor names a method of a C type `Type.method`, and `account` hands the per-module tables the LAST
    // component only. So every arm below that named a type was dead code: `DirEntry.is_dir` was compared against
    // `is_dir` and never matched, which made `os.walk` and `os.scandir` NOT PROVEN on any suite that enumerates a
    // directory -- the `_thread.lock` shape again, an entry that exists and never answers.
    // MEASURED (this branch, 37 ordinary tests under `--det`): before, `test_walk_a_tree` was NOT PROVEN with
    // "not accounted for: api:posix.DirEntry.is_dir"; after, it is covered by Level 0.
    // The entries `scandir` hands out are part of the recorded enumeration and their metadata is an `fs.stat`
    // event, which is why the answer is `Recorded` and not `Pure`.
    if let Some(answer) = type_method_account(qualname) {
        return answer;
    }
    match name {
        // file metadata: an `fs.stat` event (`<path>|<type>`, with size and mtime when the call returns them)
        "stat" | "lstat" | "fstat" | "fstatat" | "access" | "readlink" | "statvfs" | "fstatvfs" => {
            Accounting::Recorded
        }
        // directory enumeration: the order is normalised and recorded. The two types it hands back are named
        // here for the same reason `_thread.lock` is: the sensor reports a TYPE when the type itself is called,
        // and these two are constructed as part of the enumeration that is already recorded.
        "listdir" | "scandir" | "DirEntry" | "ScandirIterator" => Accounting::Recorded,
        // opening and reading a file
        "open" | "read" | "pread" | "preadv" | "readv" | "sendfile" | "copy_file_range" | "splice" => {
            Accounting::Recorded
        }
        // the environment: every read is an `env.get` / `env.has` / `env.list` event, and the value is a run input
        "getenv" | "environ" | "environb" | "putenv" | "unsetenv" => Accounting::Recorded,
        // controlled by `--det`
        "urandom" | "getrandom" => Accounting::Controlled,
        "getpid" | "getppid" | "getuid" | "geteuid" | "getgid" | "getegid" | "umask" => Accounting::Controlled,
        "cpu_count" | "process_cpu_count" | "sched_getaffinity" | "sched_setaffinity" => Accounting::Controlled,
        // pinned by `--det` (`_level0.pin_terminal_size`), same class as the host name: CI-volatile, and the
        // runner reads it to lay out its own output
        "get_terminal_size" => Accounting::Controlled,
        "uname" | "confstr" | "sysconf" | "pathconf" | "fpathconf" => Accounting::Input,
        // Starting a child the engine FOLLOWS, and reaping it. The engine runs the child under its own
        // observation and credits what it read, wrote and refused to the test that started it
        // (`Capture::credit_child`), and a follow it cannot trust sets the `spawn` flag, which refuses the
        // test by name ("subprocess") -- so the channel is decided by the predicate that actually knows,
        // per child, and not by this name. The verifier is conservative regardless: Level 0 records
        // `uncontrolled.child` for a child process, so a test that spawns one is never IDENTICAL.
        // MEASURED on this branch: reporting these as gaps made every followed-child test uncacheable
        // (tests/test_proofcache_follow.py: 14 failing against 10 before, and the 4 were exactly the ones
        // that assert a followed child's reads ARE credited as inputs and the test is reused).
        "system" | "popen" | "spawnv" | "spawnve" | "spawnvp" | "spawnvpe" | "posix_spawn" | "posix_spawnp"
        | "wait" | "wait3" | "wait4" | "waitpid" | "waitid" => Accounting::Recorded,
        // A bare `fork` with no exec is not a followed child, and `exec*` replaces this process: neither is
        // covered by the argument above, so both stay refused, as do signals to another process.
        "fork" | "forkpty" | "_exit" | "abort" | "execv" | "execve" | "execvp" | "execvpe" | "kill"
        | "killpg" => Accounting::Unaccounted,
        // writes and pure path work: a write carries no information into the test
        "write" | "pwrite" | "writev" | "pwritev" | "close" | "closerange" | "fsync" | "fdatasync" | "ftruncate"
        | "truncate" | "lseek" | "dup" | "dup2" | "pipe" | "pipe2" | "mkdir" | "makedirs" | "rmdir" | "remove"
        | "unlink" | "rename" | "replace" | "link" | "symlink" | "chmod" | "chown" | "lchown" | "fchmod"
        | "fchown" | "utime" | "mkfifo" | "mknod" | "set_inheritable"
        | "get_inheritable" | "set_blocking" | "get_blocking" | "fspath" | "strerror" => Accounting::Pure,
        // Registering a callback for fork reads nothing and returns nothing: it only has an effect if the process
        // forks, and `fork` itself is Unaccounted above, so the channel is refused where it actually opens. Named
        // here because the standard library registers these on import (`random`, `threading`, `logging`), which
        // put `api:posix.register_at_fork` on ordinary tests -- MEASURED on the smoke project (itsdangerous).
        "register_at_fork" => Accounting::Pure,
        // The decoders of a wait status: they interpret an integer the caller already has (the one `waitpid`
        // returned, which the arm above accounts for) and ask the system for nothing. `subprocess.run` calls
        // them on every child, so leaving them unnamed refused every test that ran one -- MEASURED on this
        // branch: `subprocess.run(["true"])` was NOT PROVEN with
        // "api:posix.WIFSTOPPED, api:posix.waitstatus_to_exitcode" and nothing else.
        "WIFEXITED" | "WEXITSTATUS" | "WIFSIGNALED" | "WTERMSIG" | "WIFSTOPPED" | "WSTOPSIG"
        | "WIFCONTINUED" | "WCOREDUMP" | "waitstatus_to_exitcode" => Accounting::Pure,
        // whether a descriptor is a terminal, and the encoding that implies, differ between a terminal and a pipe
        // and between machines, and `--det` pins neither
        "isatty" | "device_encoding" | "ttyname" => Accounting::Unaccounted,
        // the working directory: pinned to the project root by `--det`
        "getcwd" | "getcwdb" | "chdir" | "fchdir" => Accounting::Controlled,
        // string work on paths, no call to the operating system at all
        "_path_normpath" | "_path_splitroot_ex" | "_path_isabs" | "_path_join" | "_path_split"
        | "_path_splitext" | "_path_islink" => Accounting::Pure,
        // the result tuple types of `uname` and `stat`: carriers, pinned with the input they come from
        "uname_result" | "stat_result" | "statvfs_result" | "terminal_size" | "times_result"
        | "waitid_result" | "sched_param" => Accounting::Input,
        // extended attributes, resource limits, scheduling, the user database, terminal size: no event today
        _ => Accounting::Unaccounted,
    }
}

/// `select` and `selectors`: readiness, which is timing.
///
/// The ANSWER -- which descriptors are ready now -- is `uncontrolled.io` and stays refused. What is named here
/// is the object's own lifecycle: creating a poller and registering or unregistering a descriptor with it reads
/// nothing outside the process and returns nothing about the outside world. They are named because the standard
/// library's `subprocess` creates a poller for every child whose output is captured, so a test doing
/// `subprocess.run(..., capture_output=True)` was refused for having constructed one.
/// MEASURED on this branch, a test that captures a child's output: the refused names were exactly
/// `api:select.poll`, `api:select.poll.register` and `api:select.poll.unregister` -- the lifecycle, never the
/// wait. The wait itself (`poll.poll`, `select.select`, `epoll.poll`, `EpollSelector.select`, ...) is not named
/// here, so a test that waits for readiness is still NOT PROVEN.
fn select_account(qualname: &str, name: &str) -> Accounting {
    // `poll` is the name of BOTH the poller type and its wait (`select.poll` against `select.poll.poll`), and
    // `account` compares the last component only, so this one has to look at the owner: a bare name is the
    // type, an owned name is a method of it. Getting that wrong either way would be a false green.
    let owned = qualname.contains('.');
    match (owned, name) {
        (false, "poll" | "devpoll" | "epoll" | "kqueue") => Accounting::Pure,
        (true, "register" | "unregister" | "modify" | "close" | "fileno" | "closed" | "get_map" | "__init__"
            | "__new__" | "__enter__" | "__exit__") => Accounting::Pure,
        // the readiness answer: `poll.poll`, `select.select`, `epoll.poll`, a selector's `select`, ...
        _ => Accounting::Unaccounted,
    }
}

fn time_account(name: &str) -> Accounting {
    match name {
        // the virtual clock
        "time" | "time_ns" | "monotonic" | "monotonic_ns" | "perf_counter" | "perf_counter_ns" | "sleep"
        | "clock_gettime" | "clock_gettime_ns" | "clock_settime" | "clock_settime_ns" | "gmtime" | "localtime"
        | "mktime" | "strftime" | "strptime" | "asctime" | "ctime" | "tzset" | "clock_getres" => {
            Accounting::Controlled
        }
        // CPU time of the process and of the thread: real counters, recorded as an event (R-055 V14)
        "process_time" | "process_time_ns" | "thread_time" | "thread_time_ns" | "times" => Accounting::Recorded,
        // the machine's clock resolution and monotonic flags: no input pins them
        "get_clock_info" => Accounting::Unaccounted,
        _ => Accounting::Unaccounted,
    }
}

/// `_io`: the stream surface over data the engine already accounted for.
///
/// The claim rests on the engine's observer at `open`: the `fs.read` event carries the path and the digest of
/// what was read, so the stream methods that hand those bytes to the test add no information the verifier does
/// not already compare.
///
/// **The one place this table's claim is weaker than the rest**, stated here rather than only in the report: a
/// stream that is not a file has no such `open` behind it. A test that reads `sys.stdin` goes through the same
/// `_io` methods, and nothing records what it read. Standard input is a channel the engine already lists as
/// uncovered (`docs/VERIFY-INPUTS.md`), `builtins.input` is `Unaccounted` above, and under a test runner stdin is
/// normally closed or replaced — but a test that reads it directly is a gap this entry does not catch. Closing it
/// needs an event for stdin, not a different answer here.
fn io_account(name: &str) -> Accounting {
    match name {
        // the bytes a stream returns were accounted for when the file was opened (the `fs.read` event carries the
        // digest of what was read); a write carries nothing into the test
        "read" | "readline" | "readlines" | "readinto" | "readinto1" | "read1" | "readall" | "peek" | "write"
        | "writelines" | "seek" | "tell" | "truncate" | "flush" | "close" | "fileno" | "isatty" | "seekable"
        | "readable" | "writable" | "detach" | "reconfigure" | "getvalue" | "getbuffer" | "__init__" | "__new__"
        | "__enter__" | "__exit__" | "open_code" => Accounting::Recorded,
        "open" => Accounting::Recorded,
        // in-memory streams and the encoding helpers: a function of what is already in the process
        "StringIO" | "BytesIO" | "IncrementalNewlineDecoder" | "text_encoding" | "DEFAULT_BUFFER_SIZE" => {
            Accounting::Pure
        }
        // The stream TYPES, for the same reason `_thread.lock` had to be named: the sensor reports a type when
        // the type itself is called, and `open()` builds its stream by calling `_io.TextIOWrapper` around a
        // `_io.BufferedReader` around a `_io.FileIO`. Constructing a stream is not an observation -- the bytes
        // are, and they were accounted for at `open` (the `fs.read` event carries the digest of what was read),
        // which is why the methods above answer `Recorded` and these do too.
        // MEASURED on this branch: `python -m detpy unittest` on a project whose first test does
        // `open(path, "w").write("x")` reported `unaccounted.api: _io.TextIOWrapper`, so that test was NOT
        // PROVEN, and the refusal was carried to the test after it in the same process, which was then never
        // reused (tests/test_runners_unittest.py::test_rmtree_of_a_temporary_directory_is_not_a_write_in_the_project).
        "TextIOWrapper" | "BufferedReader" | "BufferedWriter" | "BufferedRandom" | "BufferedRWPair" | "FileIO"
        | "_IOBase" | "_RawIOBase" | "_BufferedIOBase" | "_TextIOBase" | "_BytesIOBuffer" => {
            Accounting::Recorded
        }
        // the exception types of the `_io` module: carriers of a failure, no state of their own
        "BlockingIOError" | "UnsupportedOperation" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

fn socket_account(name: &str) -> Accounting {
    match name {
        // the closed network: a connection is an event, and so is its stream; a live endpoint is marked
        "connect" | "connect_ex" | "bind" | "listen" | "accept" | "send" | "sendall" | "sendto" | "sendmsg"
        | "recv" | "recv_into" | "recvfrom" | "recvfrom_into" | "recvmsg" | "recvmsg_into" | "shutdown"
        | "close" | "detach" | "dup" | "makefile" | "__init__" | "__new__" | "socket" | "socketpair"
        | "create_connection" | "create_server" => Accounting::Recorded,
        // name resolution goes through the closed network
        "getaddrinfo" | "getnameinfo" | "gethostbyname" | "gethostbyname_ex" | "gethostbyaddr" | "getservbyname"
        | "getservbyport" | "getprotobyname" | "getfqdn" => Accounting::Recorded,
        // pinned to localhost by `--det`
        "gethostname" | "sethostname" => Accounting::Controlled,
        // byte order and address parsing
        "htons" | "htonl" | "ntohs" | "ntohl" | "inet_aton" | "inet_ntoa" | "inet_pton" | "inet_ntop"
        | "setsockopt" | "getsockopt" | "settimeout" | "gettimeout" | "setblocking" | "fileno" | "getsockname"
        | "getpeername" | "if_nametoindex" | "if_indextoname" | "if_nameindex" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

fn thread_account(name: &str) -> Accounting {
    match name {
        // a thread: `uncontrolled.thread`, already NOT PROVEN. Named so the report says "thread".
        "start_new_thread" | "start_joinable_thread" | "start" | "_set_sentinel" | "interrupt_main" => {
            Accounting::Unaccounted
        }
        // locks and thread-local storage carry no outside information; the identifier is pinned.
        //
        // `lock` and `_ThreadHandle` are the TYPES, and they are here because CPython's `threading.Lock` IS the
        // class `_thread.lock` (MEASURED on 3.13: `threading.Lock is <class '_thread.lock'>`), so a test writing
        // the most ordinary `threading.Lock()` calls the type itself and the sensor reports the type's qualified
        // name. Only the methods were listed, so constructing a lock was unaccounted and every test that took one
        // came out NOT PROVEN -- MEASURED on the smoke project (CI 44959416348: "not accounted for:
        // api:_thread.lock" on every test of itsdangerous). Creating a lock reads nothing from outside the
        // process: what a lock can make non-deterministic is the ORDER of threads, which is a different claim and
        // is refused by its own mark (`start_new_thread` above is Unaccounted, so a test that starts a thread is
        // NOT PROVEN whatever it does with locks).
        "allocate_lock" | "RLock" | "LockType" | "acquire" | "release" | "locked" | "__enter__" | "__exit__"
        | "get_ident" | "get_native_id" | "stack_size" | "_count" | "_local" | "TIMEOUT_MAX"
        | "daemon_threads_allowed" => Accounting::Controlled,
        // The lock TYPE itself, because `threading.Lock` IS `_thread.lock` in CPython (MEASURED on 3.13:
        // `threading.Lock is <class '_thread.lock'>`), so the most ordinary `threading.Lock()` calls the type and
        // the sensor reports the type's name, not a method's. Only the methods were listed, so creating a lock
        // was unaccounted and every test that took one came out NOT PROVEN -- MEASURED on the smoke project (CI
        // 44959416348: "not accounted for: api:_thread.lock" on every test of itsdangerous).
        //
        // `Pure` and not `Controlled`, because no control pins anything here: allocating a lock is a function of
        // what is already in the process and reads nothing from outside it. What a lock can make
        // non-deterministic is the ORDER of threads, which is a different claim and is refused by its own name:
        // `start_new_thread` and `start_joinable_thread` are Unaccounted above, so a test that starts a thread is
        // NOT PROVEN whatever it then does with locks. `_ThreadHandle` is deliberately NOT listed: its `is_done`
        // reports whether another thread has finished, which is timing, and a handle can reach a test from a
        // thread the runner started.
        "lock" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

fn random_account(name: &str) -> Accounting {
    match name {
        // seeded per test by `--det`
        "random" | "seed" | "getstate" | "setstate" | "getrandbits" | "randrange" | "randint" | "choice"
        | "choices" | "shuffle" | "sample" | "uniform" | "triangular" | "betavariate" | "expovariate"
        | "gammavariate" | "gauss" | "lognormvariate" | "normalvariate" | "vonmisesvariate" | "paretovariate"
        | "weibullvariate" | "binomialvariate" | "randbytes" | "__init__" | "__new__" | "Random" => {
            Accounting::Controlled
        }
        // SystemRandom reads the operating system's entropy, which `--det` controls by default and leaves real
        // under `--det-entropy=observe`, where every read is an event
        "SystemRandom" => Accounting::Controlled,
        _ => Accounting::Unaccounted,
    }
}

fn sqlite_account(name: &str) -> Accounting {
    match name {
        // the database file is read like a file (R-055 V7)
        "connect" | "Connection" | "__init__" | "__new__" => Accounting::Recorded,
        // everything the C library then does inside that file it does in C, with no event: the declared residual
        "enable_load_extension" | "load_extension" => Accounting::Unaccounted,
        "complete_statement" | "register_adapter" | "register_converter" | "adapt" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

fn sys_account(name: &str) -> Accounting {
    match name {
        "getsizeof" | "intern" | "exc_info" | "exception" | "audit" | "is_finalizing" | "getrecursionlimit"
        | "setrecursionlimit" | "getdefaultencoding" | "getfilesystemencoding" | "getfilesystemencodeerrors"
        | "_getframe" | "_getframemodulename" | "displayhook" | "excepthook" | "unraisablehook" | "exit"
        | "getrefcount" | "_clear_type_cache" | "_is_gil_enabled" | "get_int_max_str_digits"
        | "set_int_max_str_digits" | "_base_executable" => Accounting::Pure,
        // the interpreter's identity is a run input
        "version_info" | "implementation" | "getwindowsversion" | "getandroidapilevel" => Accounting::Input,
        // tracing and profiling hooks, the asynchronous generator hooks, the audit hook registry, the thread
        // switch interval and the frames of other threads: process state the engine makes no claim about
        _ => Accounting::Unaccounted,
    }
}

fn gc_account(name: &str) -> Accounting {
    match name {
        // these hand out the heap: object identity and allocation order leak through them
        "get_objects" | "get_referrers" | "get_referents" | "get_stats" => Accounting::Unaccounted,
        "collect" | "disable" | "enable" | "isenabled" | "freeze" | "unfreeze" | "get_freeze_count"
        | "set_debug" | "get_debug" | "set_threshold" | "get_threshold" | "get_count" | "is_tracked"
        | "is_finalized" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

fn resource_account(name: &str) -> Accounting {
    match name {
        // real memory and I/O counters, recorded as an event (R-055 V14)
        "getrusage" => Accounting::Recorded,
        "getrlimit" | "setrlimit" | "getpagesize" => Accounting::Input,
        _ => Accounting::Unaccounted,
    }
}

fn import_account(name: &str) -> Accounting {
    match name {
        // the import system: what it loads is `inputs.code` (the project's own source) and `inputs.deps`
        // (everything else), both run inputs the verifier compares
        "create_dynamic" | "create_builtin" | "exec_dynamic" | "exec_builtin" | "init_frozen" | "get_frozen_object"
        | "is_builtin" | "is_frozen" | "is_frozen_package" | "_fix_co_filename" | "source_hash"
        | "check_hash_based_pycs" | "acquire_lock" | "release_lock" | "lock_held" | "extension_suffixes"
        | "find_spec" | "find_frozen" | "load_module" | "exec_module" | "create_module" | "module_from_spec"
        | "import_module"
        | "reload" | "invalidate_caches" | "loads" | "dumps" | "load" | "dump" | "zipimporter"
        | "get_data" | "get_code" | "get_source" | "get_filename" | "is_package" | "_imp" => Accounting::Input,
        _ => Accounting::Unaccounted,
    }
}

fn ssl_account(name: &str) -> Accounting {
    match name {
        // TLS over the closed network: the cassette records and replays it
        "wrap_socket" | "wrap_bio" | "read" | "write" | "do_handshake" | "unwrap" | "shutdown" | "pending"
        | "getpeercert" | "cipher" | "version" | "selected_alpn_protocol" | "shared_ciphers"
        | "_create_default_https_context" | "SSLContext" | "__new__" | "__init__" => Accounting::Recorded,
        // the trust store is read from disk and the random pool is the operating system's
        "load_verify_locations" | "load_cert_chain" | "load_default_certs" | "set_default_verify_paths"
        | "get_default_verify_paths" | "enum_certificates" | "enum_crls" | "RAND_bytes" | "RAND_pseudo_bytes"
        | "RAND_add" | "RAND_status" | "RAND_egd" => Accounting::Unaccounted,
        _ => Accounting::Unaccounted,
    }
}

// ---------------------------------------------------------------------------------------------------------------
// The Node half of the same table.
//
// The argument is the one above, with JavaScript's boundary in place of Python's: a test can only reach outside
// state through a builtin module (`node:fs`, `node:os`, ...), a global the engine controls (`Date`, `Math`,
// `crypto`, `performance`, `process`), or a native addon. Which builtin modules exist, and what they export, is
// fixed by the `runtime` input (the Node version), so the surface is finite and auditable, and
// `AUDITED_RUNTIMES` refuses a version nobody checked.
//
// The difference from Python is where the per-name wrapping happens: Node's builtin exports are writable, so the
// shell can replace the ones this table does not account for with a wrapper that marks the test. CPython's C
// types are immutable, which is why the Python side watches calls instead.
// ---------------------------------------------------------------------------------------------------------------

/// Builtin modules whose whole surface is a function of its arguments: text, numbers, containers, streams over
/// data already in the process, serialisation, compression, assertions, events.
const NODE_PURE_MODULES: &[&str] = &[
    "assert", "assert/strict", "buffer", "console", "constants", "diagnostics_channel", "events", "path",
    "path/posix", "path/win32", "punycode", "querystring", "stream", "stream/consumers", "stream/promises",
    "stream/web", "string_decoder", "url", "util", "util/types", "zlib",
];

/// Native addons audited one by one by MEASURING what they ask the operating system for (founder decision,
/// 2026-11-21, route 1). An addon that is not here is the declared residual: its C++ reads are invisible to
/// every in-process sensor, so loading it makes every test of the run NOT PROVEN. Each entry is a marker that
/// must appear in the path `process.dlopen` is given; the evidence for each is in docs/NATIVE-AUDITS.md, and a
/// hand audit is OUR PROMISE, not a proof -- only a syscall-level sensor turns it into one.
pub const NODE_AUDITED_NATIVE: &[&str] = &[
    // The engine's own addon. It was escaping only by timing (loaded before the sensor starts), which is not a
    // reason: it is named here so that an engine loaded later, or re-loaded in a worker, is still exempt.
    "/libdetpy_node.so",
    "/libdetpy_node.dylib",
    "/detjs.linux-x64.node",
    "/detjs.linux-arm64.node",
    "/detjs.darwin-arm64.node",
    // jest 30's module resolver (`jest-resolve` -> `unrs-resolver`), which is also vitest's. Without this
    // entry NO test of a jest 30 suite can ever be proven, cached or spread across cores, because the runner
    // loads it before the first test runs.
    "/node_modules/@unrs/resolver-binding-",
];

/// Whether the addon at this path is one of the audited ones ([`NODE_AUDITED_NATIVE`]).
pub fn node_native_audited(path: &str) -> bool {
    NODE_AUDITED_NATIVE.iter().any(|m| path.contains(m))
}

/// Builtin modules that reach outside state: every export must be named below, and anything unnamed makes the
/// test NOT PROVEN.
const NODE_ENUMERATED_MODULES: &[&str] = &[
    "async_hooks", "child_process", "cluster", "crypto", "dgram", "dns", "dns/promises", "fs", "fs/promises",
    "http", "http2", "https", "inspector", "inspector/promises", "module", "net", "os", "perf_hooks", "process",
    "readline", "readline/promises", "repl", "sqlite", "test", "timers", "timers/promises", "tls", "trace_events",
    "tty", "v8", "vm", "wasi", "worker_threads",
];

/// How a Node builtin module is treated as a whole: `pure`, `enumerated` or `unknown`.
///
/// The shell needs this as well as [`account_node`], because the two call for different action. An `unknown`
/// module is one the table has no rule for at all, so reaching it is itself the gap and the shell marks the test
/// on load. An `enumerated` module has rules, and the shell wraps only the exports that come back unaccounted --
/// `child_process` is entirely unaccounted by design (any child process is), but merely loading it is not yet
/// using it, and the runner loads it for its own reasons.
pub fn node_module_policy(module: &str) -> &'static str {
    let m = module.strip_prefix("node:").unwrap_or(module);
    if NODE_PURE_MODULES.contains(&m) {
        "pure"
    } else if NODE_ENUMERATED_MODULES.contains(&m) {
        "enumerated"
    } else {
        "unknown"
    }
}

/// Classify one export of one Node builtin module (`os`, `hostname`), the `node:` prefix already removed.
///
/// Same contract as [`account`]: anything this table does not list is [`Accounting::Unaccounted`], and the shell
/// wraps those so that calling one marks the test.
pub fn account_node(module: &str, export: &str) -> Accounting {
    let m = module.strip_prefix("node:").unwrap_or(module);
    if NODE_PURE_MODULES.contains(&m) {
        return Accounting::Pure;
    }
    if !NODE_ENUMERATED_MODULES.contains(&m) {
        return Accounting::Unaccounted;
    }
    match m {
        // Context propagation across an async boundary. The module was in the enumerated list with NOT ONE export
        // named, which means default-deny answered for all of them -- correct by construction and very expensive:
        // Node's own stream internals construct an `AsyncResource`, so every test that read a file through
        // `fs.createReadStream` was NOT PROVEN and was never cached. MEASURED on this branch before this arm
        // (node/test/cache.test.js, "content read, read-write open, stream, listing, existence and link target
        // are inputs"): "a Level 0 control could not be installed: not accounted for: api:async_hooks.AsyncResource",
        // one file re-running instead of being reused, on both the Vitest and the Jest leg. `node:test` itself
        // reaches it through `Test.runInAsyncScope`.
        //
        // What these do is carry the CALLER's context into a callback or a continuation: they move a value that is
        // already in this process from one place in it to another. They read nothing outside the process and they
        // pin nothing, which is `Pure`.
        //
        // What stays refused, and why, because this is the line that matters here: `createHook` observes every
        // async resource the runtime creates, and `executionAsyncId` / `triggerAsyncId` /
        // `executionAsyncResource` hand the test the ids the runtime assigned. Those are the engine's own
        // scheduling, which no run input pins and no event records, so a test that asks for one is NOT PROVEN.
        "async_hooks" => match export {
            "AsyncResource" | "AsyncLocalStorage" | "asyncWrapProviders" | "runInAsyncScope" | "emitDestroy"
            | "bind" | "snapshot" | "run" | "exit" | "enterWith" | "getStore" | "disable" | "enable" => {
                Accounting::Pure
            }
            _ => Accounting::Unaccounted,
        },
        "os" => match export {
            // the engine's `facts.js` records what these answered, and `--det` pins the volatile ones
            "hostname" | "userInfo" | "homedir" | "tmpdir" | "networkInterfaces" | "availableParallelism"
            | "totalmem" | "freemem" | "loadavg" | "uptime" | "release" | "version" | "machine" | "type"
            | "arch" | "endianness" | "platform" | "cpus" | "getPriority" | "setPriority" | "setDefaultAutoSelectFamily"
            | "getDefaultAutoSelectFamily" => Accounting::Recorded,
            "EOL" | "constants" | "devNull" => Accounting::Pure,
            _ => Accounting::Unaccounted,
        },
        "fs" | "fs/promises" => match export {
            // reads and metadata: an `fs.read` / `fs.stat` event with the path and the digest of the bytes
            "readFile" | "readFileSync" | "read" | "readSync" | "readv" | "readvSync" | "open" | "openSync"
            | "openAsBlob" | "createReadStream" | "readdir" | "readdirSync" | "opendir" | "opendirSync"
            | "stat" | "statSync" | "lstat" | "lstatSync" | "fstat" | "fstatSync" | "statfs" | "statfsSync"
            | "exists" | "existsSync" | "access" | "accessSync" | "realpath" | "realpathSync" | "readlink"
            | "readlinkSync" | "glob" | "globSync" | "close" | "closeSync" | "fsync" | "fsyncSync"
            | "fdatasync" | "fdatasyncSync" | "lchmod" | "promises" => Accounting::Recorded,
            // writes and the rest of the mutations: they carry nothing from outside into the test
            "writeFile" | "writeFileSync" | "write" | "writeSync" | "writev" | "writevSync" | "appendFile"
            | "appendFileSync" | "createWriteStream" | "mkdir" | "mkdirSync" | "mkdtemp" | "mkdtempSync"
            | "rm" | "rmSync" | "rmdir" | "rmdirSync" | "unlink" | "unlinkSync" | "rename" | "renameSync"
            | "copyFile" | "copyFileSync" | "cp" | "cpSync" | "truncate" | "truncateSync" | "ftruncate"
            | "ftruncateSync" | "chmod" | "chmodSync" | "fchmod" | "fchmodSync" | "chown" | "chownSync"
            | "fchown" | "fchownSync" | "lchown" | "lchownSync" | "utimes" | "utimesSync" | "futimes"
            | "futimesSync" | "lutimes" | "lutimesSync" | "link" | "linkSync" | "symlink" | "symlinkSync"
            | "constants" | "Dirent" | "Stats" | "Dir" | "ReadStream" | "WriteStream" | "FileReadStream"
            | "FileWriteStream" | "F_OK" | "R_OK" | "W_OK" | "X_OK" => Accounting::Pure,
            // the file system as an event source: when a change arrives is not controlled
            "watch" | "watchFile" | "unwatchFile" => Accounting::Unaccounted,
            _ => Accounting::Unaccounted,
        },
        "net" | "tls" | "http" | "https" | "http2" | "dgram" => match export {
            // the closed network: a connection is an event and so is its stream
            "connect" | "createConnection" | "createServer" | "createSecureServer" | "createSecureContext"
            | "Socket" | "Server" | "TLSSocket" | "Agent" | "request" | "get" | "createSocket" | "ClientRequest"
            | "ServerResponse" | "IncomingMessage" | "OutgoingMessage" | "globalAgent" | "STATUS_CODES"
            | "METHODS" | "maxHeaderSize" | "setDefaultAutoSelectFamily" | "getDefaultAutoSelectFamily"
            | "setDefaultAutoSelectFamilyAttemptTimeout" | "getDefaultAutoSelectFamilyAttemptTimeout"
            | "validateHeaderName" | "validateHeaderValue" | "connectSync" | "BlockList" | "SocketAddress"
            | "rootCertificates" | "DEFAULT_CIPHERS" | "DEFAULT_ECDH_CURVE" | "DEFAULT_MAX_VERSION"
            | "DEFAULT_MIN_VERSION" | "checkServerIdentity" | "constants" | "sessionIdContext" => {
                Accounting::Recorded
            }
            "isIP" | "isIPv4" | "isIPv6" => Accounting::Pure,
            // the module's own argument normalisation (`net._normalizeArgs`): a function of its arguments, and
            // whatever it is normalising for is recorded at the call it leads to
            "_normalizeArgs" | "_createServerHandle" | "_setSimultaneousAccepts" => Accounting::Pure,
            _ => Accounting::Unaccounted,
        },
        "dns" | "dns/promises" => match export {
            "lookup" | "lookupService" | "resolve" | "resolve4" | "resolve6" | "resolveAny" | "resolveCname"
            | "resolveMx" | "resolveNaptr" | "resolveNs" | "resolvePtr" | "resolveSoa" | "resolveSrv"
            | "resolveTxt" | "resolveCaa" | "reverse" | "Resolver" | "promises" => Accounting::Recorded,
            "getServers" | "setServers" | "setDefaultResultOrder" | "getDefaultResultOrder" => Accounting::Input,
            _ => Accounting::Unaccounted,
        },
        "crypto" => match export {
            // entropy: controlled by `--det`, or observed with an event under `--det-entropy=observe`
            "randomBytes" | "randomFillSync" | "randomFill" | "randomInt" | "randomUUID" | "getRandomValues"
            | "pseudoRandomBytes" | "prng" | "rng" => Accounting::Controlled,
            // key generation draws from the same entropy; the engine marks what it cannot control
            "generateKey" | "generateKeyPair" | "generateKeySync" | "generateKeyPairSync" | "generatePrime"
            | "generatePrimeSync" | "webcrypto" | "subtle" => Accounting::Recorded,
            // everything else is a function of its input: digests, ciphers, signatures, key import and export
            "createHash" | "createHmac" | "createCipheriv" | "createDecipheriv" | "createSign" | "createVerify"
            | "createDiffieHellman" | "createDiffieHellmanGroup" | "createECDH" | "createPrivateKey"
            | "createPublicKey" | "createSecretKey" | "sign" | "verify" | "publicEncrypt" | "publicDecrypt"
            | "privateEncrypt" | "privateDecrypt" | "diffieHellman" | "hash" | "hkdf" | "hkdfSync" | "pbkdf2"
            | "pbkdf2Sync" | "scrypt" | "scryptSync" | "timingSafeEqual" | "checkPrime" | "checkPrimeSync"
            | "getCiphers" | "getCurves" | "getHashes" | "getCipherInfo" | "getFips" | "setFips"
            | "constants" | "Certificate" | "X509Certificate" | "KeyObject" | "Hash" | "Hmac" | "Cipher"
            | "Decipher" | "Sign" | "Verify" | "DiffieHellman" | "ECDH" | "secureHeapUsed"
            | "setEngine" | "fips" => Accounting::Pure,
            _ => Accounting::Unaccounted,
        },
        // a child process or a thread: `uncontrolled.child` / `uncontrolled.thread`, already NOT PROVEN
        "child_process" | "cluster" => Accounting::Unaccounted,
        "worker_threads" => match export {
            "threadId" | "isMainThread" | "isInternalThread" | "resourceLimits" | "SHARE_ENV" => {
                Accounting::Controlled
            }
            // Node's own ESM loader talks to its hooks thread with this, synchronously, on every `import()`
            // that goes through a registered hook. What it carries is the module's resolution and its source,
            // which the engine records as `inputs.code` / `inputs.deps` -- the same answer, for the same
            // reason, as the `module._*` loader internals above.
            // MEASURED, CI 44981148907 and locally on node 22: an AVA project whose test does a dynamic
            // `import()` was NOT PROVEN with "api:worker_threads.receiveMessageOnPort", so no AVA suite could
            // be cached (AVA registers a loader hook; the deprecation warning `module.register()` in the same
            // log is that thread).
            // A test that reads a message from a worker of its own is refused where that opens: `Worker`
            // itself is Unaccounted (below), as are `parentPort`, `MessageChannel` and `postMessage`.
            "receiveMessageOnPort" => Accounting::Input,
            _ => Accounting::Unaccounted,
        },
        "process" => match export {
            // the environment: every read is an event, and the value is a run input
            "env" | "loadEnvFile" => Accounting::Recorded,
            // real counters, recorded as events (`facts.js`)
            "cpuUsage" | "memoryUsage" | "resourceUsage" | "constrainedMemory" | "availableMemory"
            | "getActiveResourcesInfo" => Accounting::Recorded,
            // pinned or virtual under `--det`
            "hrtime" | "uptime" | "pid" | "ppid" | "cwd" | "chdir" | "umask" | "getuid" | "geteuid" | "getgid"
            | "getegid" | "getgroups" | "setuid" | "setgid" | "title" => Accounting::Controlled,
            // `binding` hands out a raw internal binding, bypassing the patched modules, so the decision is
            // per ARGUMENT and the engine's wrapper makes it (node/src/facts.js): `constants` is a table of
            // numbers pinned by the `runtime` input and is recorded; every other binding marks the test
            // `uncontrolled.io`. Emscripten's generated code -- PGlite, which the pilot's suite runs on --
            // asks for `constants`, and without this every test of such a suite was NOT PROVEN.
            "binding" => Accounting::Controlled,
            // Loading a native addon. The addon's own path and digest are a run input, and whether its C code
            // is reasoned about is decided by the native rule, which reports `native:<path>` for anything not
            // on the audited list -- so the refusal is made there, by the predicate that knows which addon it
            // was, and this name adds a second reason for the same thing. MEASURED: a better-sqlite3 test was
            // refused twice over, "api:process.dlopen (and 1 more)" on one runner and the native rule on the
            // other, for one act.
            "dlopen" => Accounting::Recorded,
            // hands out a builtin module: what is in it is this table's own business, and what was loaded is
            // `inputs.code` / `inputs.deps`
            "getBuiltinModule" => Accounting::Input,
            // the run's identity, compared as run inputs
            "argv" | "argv0" | "execPath" | "execArgv" | "version" | "versions" | "platform" | "arch"
            | "config" | "release" | "features" | "allowedNodeEnvironmentFlags" | "debugPort" => Accounting::Input,
            // bookkeeping that carries nothing from outside
            "nextTick" | "on" | "once" | "off" | "emit" | "removeListener" | "removeAllListeners" | "exit"
            | "exitCode" | "emitWarning" | "stdout" | "stderr" | "hasUncaughtExceptionCaptureCallback"
            | "setUncaughtExceptionCaptureCallback" | "listeners" | "listenerCount" | "eventNames"
            | "prependListener" | "prependOnceListener" | "setMaxListeners" | "getMaxListeners"
            | "addListener" | "kill" | "abort" | "noDeprecation" | "throwDeprecation" | "traceDeprecation"
            | "finalization" | "permission" => Accounting::Pure,
            // the runner's own plumbing: the worker channel it talks to its parent over, and the handle lists it
            // uses to decide when a file is done. The runner's identity is a run input and nothing writes its
            // environment during a run (Rule E), so these are the declared controlled set, not a test's channel.
            "_send" | "_getActiveHandles" | "_getActiveRequests" | "_tickCallback" | "channel" | "connected"
            | "disconnect" | "send" => Accounting::Controlled,
            // the standard input, a native addon, the internal bindings, a diagnostic report: nothing covers them
            // (`dlopen` and `binding` are answered by their own arms above, where the predicate that knows
            // which addon or which binding it was makes the decision)
            "stdin" | "_linkedBinding" | "report" | "setSourceMapsEnabled"
            | "sourceMapsEnabled" | "initgroups" | "setgroups" | "ref" | "unref" | "_debugProcess"
            | "_debugEnd" | "_rawDebug" | "reallyExit" | "_kill" | "_fatalException"
            | "_stopProfilerIdleNotifier" | "_startProfilerIdleNotifier" => Accounting::Unaccounted,
            _ => Accounting::Unaccounted,
        },
        "timers" | "timers/promises" => match export {
            // the virtual clock drives the timers
            "setTimeout" | "setInterval" | "setImmediate" | "clearTimeout" | "clearInterval" | "clearImmediate"
            | "scheduler" | "promises" | "active" | "unenroll" | "enroll" => Accounting::Controlled,
            _ => Accounting::Unaccounted,
        },
        "perf_hooks" => match export {
            "performance" | "now" | "timeOrigin" | "timerify" | "mark" | "measure" | "clearMarks"
            | "clearMeasures" | "constants" => Accounting::Controlled,
            // the event loop's own timing and the observer stream: scheduling, which Level 0 does not control
            "monitorEventLoopDelay" | "PerformanceObserver" | "createHistogram" | "eventLoopUtilization" => {
                Accounting::Unaccounted
            }
            _ => Accounting::Unaccounted,
        },
        // A vm context of the code under test is not outside the engine: `children.js` installs the Level 0
        // controls into every one it creates, and a context it cannot reach is already reported
        // (`uncontrolled.level0`). Compiling code carries no outside information either -- the code itself is
        // `inputs.code`. What is left is the heap, which nothing pins.
        "vm" => match export {
            "createContext" | "runInNewContext" | "runInContext" | "runInThisContext" | "compileFunction"
            | "Script" | "createScript" | "isContext" | "SourceTextModule" | "SyntheticModule" | "Module"
            | "USE_MAIN_CONTEXT_DEFAULT_LOADER" => Accounting::Controlled,
            "constants" => Accounting::Pure,
            _ => Accounting::Unaccounted,
        },
        "module" => match export {
            // the loader's own internals, which the runner and Node itself call constantly: what they resolve and
            // load is `inputs.code` and `inputs.deps`, the run inputs the verifier compares. Matched by prefix
            // because the set differs between Node versions (`_readPackage` is not in every one) and every member
            // of it is the same claim.
            _ if export.starts_with('_') => Accounting::Input,
            "globalPaths" | "runMain" | "wrapper" => Accounting::Input,
            // what was loaded is `inputs.code` and `inputs.deps`
            "builtinModules" | "createRequire" | "isBuiltin" | "syncBuiltinESMExports" | "findSourceMap"
            | "SourceMap" | "Module" | "register" | "registerHooks" | "wrap" | "getCompileCacheDir"
            | "enableCompileCache" | "flushCompileCache" | "stripTypeScriptTypes" | "findPackageJSON"
            | "constants" | "getSourceMapsSupport" | "setSourceMapsSupport" => Accounting::Input,
            _ => Accounting::Unaccounted,
        },
        "wasi" => match export {
            // The engine replaces `random_get` and `clock_time_get` on every instance's import object and
            // records both (src/wasi.js), under the `seeds` and `time` controls that `required_controls`
            // already demands of a Node run. What it does NOT observe is a filesystem given through
            // `preopens`, so each import that reaches one marks the running test `uncontrolled.io` at its own
            // call: a module that only draws entropy and reads the clock is provable, one that opens a file
            // is not.
            // MEASURED on this branch (and at its base, where both runner legs failed): a WASI test was NOT
            // PROVEN with "api:wasi.WASI" although every value it read was virtual and recorded -- the class
            // itself was the only thing left unaccounted (test/network-p041.test.js, audit gap G-1429).
            "WASI" => Accounting::Controlled,
            _ => Accounting::Unaccounted,
        },
        "v8" => match export {
            // Turning a value this process already has into bytes and back. It reads nothing outside the
            // process and pins nothing; what it serialises came from somewhere the engine accounts for
            // already. Named because a runner uses it to pass values between a worker and the main process:
            // MEASURED, CI 44981148907 `node (26, shard 2/4)`, "not accounted for: api:v8.deserialize" on
            // every test of an AVA project, so nothing of that suite could be cached.
            "serialize" | "deserialize" | "Serializer" | "Deserializer" | "DefaultSerializer"
            | "DefaultDeserializer" => Accounting::Pure,
            // the heap, the coverage tables, the flags: machine state with no event
            _ => Accounting::Unaccounted,
        },
        // the heap, another realm, the debugger, the tracer, a terminal, an interactive loop, a bundled
        // database, the test runner's own hooks and the async scheduling graph: no event covers any of them
        _ => Accounting::Unaccounted,
    }
}

/// Digest of everything this table claims, so a shell cannot be built against one version of it and judged
/// against another. The shell writes the value it was built with into the trace header; [`judge`] refuses a trace
/// whose digest is not this one.
pub fn surface_digest() -> String {
    // A build constant, so it is derived once. `judge` asks for it on every test of every run, and deriving it
    // costs about 18 us, which a large verify would spend tens of thousands of times over.
    static CACHED: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    CACHED.get_or_init(derive_surface_digest).clone()
}

fn derive_surface_digest() -> String {
    let mut buf = Vec::new();
    buf.extend_from_slice(&SENSOR_CONTRACT.to_le_bytes());
    for part in [AUDITED_RUNTIMES, PURE_MODULES, INFRA_PREFIXES, CONTROLLED_NATIVE, NODE_PURE_MODULES,
                 NODE_ENUMERATED_MODULES, NODE_AUDITED_NATIVE]
    {
        buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
        for s in part {
            buf.extend_from_slice(s.as_bytes());
            buf.push(0);
        }
    }
    // the per-name arms, probed through the public entry points so the digest follows any change to them
    for (m, q) in PROBE_NAMES {
        buf.extend_from_slice(m.as_bytes());
        buf.push(b'.');
        buf.extend_from_slice(q.as_bytes());
        buf.push(b'=');
        buf.extend_from_slice(account(m, q).as_str().as_bytes());
        buf.push(0);
    }
    for (m, q) in NODE_PROBE_NAMES {
        buf.extend_from_slice(b"node:");
        buf.extend_from_slice(m.as_bytes());
        buf.push(b'.');
        buf.extend_from_slice(q.as_bytes());
        buf.push(b'=');
        buf.extend_from_slice(account_node(m, q).as_str().as_bytes());
        buf.push(0);
    }
    digest_bytes(&buf).short()
}

/// Names the surface digest probes: one per enumerated module and per decision that matters, so that changing an
/// arm changes the digest and an older shell is refused instead of silently judged by a newer table.
const PROBE_NAMES: &[(&str, &str)] = &[
    ("builtins", "open"),
    ("builtins", "input"),
    ("builtins", "id"),
    ("builtins", "list.append"),
    ("posix", "stat"),
    ("posix", "listdir"),
    ("posix", "fork"),
    ("posix", "getxattr"),
    ("posix", "urandom"),
    ("posix", "uname"),
    ("time", "time"),
    ("time", "process_time"),
    ("_io", "read"),
    ("_socket", "connect"),
    ("_socket", "gethostname"),
    ("_thread", "start_new_thread"),
    ("_random", "random"),
    ("select", "select"),
    ("_sqlite3", "connect"),
    ("sys", "settrace"),
    ("gc", "get_objects"),
    ("resource", "getrusage"),
    ("_imp", "create_dynamic"),
    ("_ssl", "RAND_bytes"),
    ("pwd", "getpwuid"),
    ("datetime", "now"),
];

/// The same, for the Node half.
const NODE_PROBE_NAMES: &[(&str, &str)] = &[
    ("os", "hostname"),
    ("os", "EOL"),
    ("fs", "readFileSync"),
    ("fs", "writeFileSync"),
    ("fs", "watch"),
    ("net", "connect"),
    ("dns", "lookup"),
    ("crypto", "randomBytes"),
    ("crypto", "createHash"),
    ("child_process", "spawn"),
    ("worker_threads", "Worker"),
    ("worker_threads", "threadId"),
    ("process", "env"),
    ("process", "dlopen"),
    ("process", "hrtime"),
    ("timers", "setTimeout"),
    ("perf_hooks", "monitorEventLoopDelay"),
    ("module", "createRequire"),
    ("path", "join"),
    ("v8", "serialize"),
    ("vm", "runInNewContext"),
    ("inspector", "open"),
];

/// The `--det` controls the table's `Controlled` answers rest on, for a given sensor.
///
/// Every `Controlled` answer is a promise that `--det` gave both runs the same value, and every one of those
/// promises is kept by a control the user can switch off (`--det-disable`). With the control off there is no
/// patch, so no event and no pinned value either -- and the table would still answer `Controlled`, which would be
/// a false IDENTICAL. So `judge` refuses a run that is missing any of these before it looks at a single name.
///
/// The two shells pin different things (Node pins the host name and the CPU count unconditionally, where Python
/// does it under `env`), so the list is per sensor; it stays here rather than in the shells, because this is part
/// of the rule.
pub fn required_controls(sensor: &str) -> &'static [&'static str] {
    if sensor.starts_with("py-") {
        // time: the virtual clock. seeds: the generators. fs: enumeration order. net: the closed network.
        // env: environment reads, the host name, the CPU count, the terminal size. os: the stat observer, the
        // pinned process id and working directory. tz / locale: pinned. hashseed: `builtins.hash`.
        &["time", "seeds", "fs", "net", "env", "os", "tz", "locale", "hashseed"]
    } else if sensor.starts_with("node-") || sensor == SENSOR_CACHE_REUSE {
        // `cache-reuse/1` runs no test of its own, but the entries it serves were keyed under the controls of
        // the session that recorded them, so a run that switched one off is not the run those entries stand for.
        &["time", "seeds", "fs", "net", "timers"]
    } else {
        // A sensor the core has no rule for. `judge` refuses it by name in clause 1, and this branch is written
        // to fail CLOSED all the same: R-058 #4 was exactly a permissive fallback whose safety argument was a
        // comment about a check that did not exist. Asking for every control both shells rest on means that if
        // this list is ever reached, the answer is a refusal and not a free pass.
        &["time", "seeds", "fs", "net", "env", "os", "tz", "locale", "hashseed", "timers"]
    }
}

/// The sensor a Node run declares when every test came from the cache, so no process watched anything
/// (`node/src/session.js`, `provableField`).
pub const SENSOR_CACHE_REUSE: &str = "cache-reuse/1";

/// Does this core have a rule for this sensor?
///
/// The accounting table is written against a known set of shells: `account`/`account_node` answer for the
/// callables THOSE shells can report, and [`required_controls`] names the controls THOSE shells' `Controlled`
/// answers rest on. A name outside the set is a shell this core knows nothing about, so nothing it reports can be
/// read as evidence -- the answer is NOT PROVEN, which is what `docs/` and `prompts/COMMON-BLOCKS.md` have always
/// declared and what R-058 #4 found was not true in the code.
pub fn sensor_known(sensor: &str) -> bool {
    sensor.starts_with("py-") || sensor.starts_with("node-") || sensor == SENSOR_CACHE_REUSE
}

/// What one shell reports about one test, and what the run as a whole declared about its sensor.
///
/// Everything here is a statement of fact by the shell. The decision is [`judge`]'s alone.
#[derive(Clone, Debug, Default)]
pub struct Attestation<'a> {
    /// `meta.provable.sensor`: the sensor the run had, e.g. `py-monitoring/1`. `None` = the run declared none.
    pub sensor: Option<&'a str>,
    /// `meta.provable.contract`: the contract version the shell was built against.
    pub contract: Option<u32>,
    /// `meta.provable.surface`: the digest of the table the shell was built against.
    pub surface: Option<&'a str>,
    /// `meta.provable.runtime`: the runtime key the run names, matched against [`AUDITED_RUNTIMES`].
    pub runtime: Option<&'a str>,
    /// `meta.controls`: the `--det` controls the run had on. Every entry of [`required_controls`] must be here.
    pub controls: &'a [String],
    /// Per test: what the sensor saw and could not place, already named (`api:posix.getxattr`,
    /// `module:ctypes`, `native:lxml.etree`, `audit:os.getxattr`).
    pub unaccounted: &'a [String],
    /// Per test: the `uncontrolled.*` kinds of the existing channel rules (`thread`, `child`, `io`, `env`, ...).
    pub marks: &'a [String],
    /// Run-wide: `not_proven_outside_tests` (an uncontrolled read while no test was running).
    pub outside: &'a [String],
}

/// The verdict of the rule for one test.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Verdict {
    /// Everything the test did is accounted for. The test may be reported identical if nothing else differs.
    Provable,
    /// Something is not accounted for. The test is NOT PROVEN, whatever its fingerprint.
    NotProven {
        /// The class of the gap, used as the verifier's reason: `sensor`, `runtime`, `api`, `module`, `native`,
        /// `audit`, `thread`, `child`, `io`, `env`, ...
        kind: String,
        /// One line naming what was not accounted for.
        detail: String,
    },
}

impl Verdict {
    pub fn is_provable(&self) -> bool {
        matches!(self, Verdict::Provable)
    }
}

fn not_proven(kind: &str, detail: String) -> Verdict {
    Verdict::NotProven { kind: kind.to_string(), detail }
}

/// The one predicate. A test is provable only when every clause below holds.
///
/// The order of the clauses is the order of the questions: did this run have a sensor the core understands; was it
/// a runtime the table was audited against; is there a channel rule that already names the gap; did the wide
/// sensor see anything it could not place; did something happen outside the tests. The first clause that fails is
/// the answer, so the report names the most fundamental gap rather than a symptom of it, and the most specific
/// name the engine has rather than the generic one.
pub fn judge(att: &Attestation<'_>) -> Verdict {
    // 1. No sensor, or one built against a different table: the core will not guess what was looked at.
    let Some(sensor) = att.sensor.filter(|s| !s.is_empty()) else {
        return not_proven(
            "sensor",
            "the run declared no sensor: nothing shows what the test did, so it cannot be shown identical".into(),
        );
    };
    if !sensor_known(sensor) {
        return not_proven(
            "sensor",
            format!(
                "sensor {sensor} is not one this core has a rule for: the accounting table was not written \
                 against it, so what it reports cannot be read as evidence"
            ),
        );
    }
    match att.contract {
        Some(SENSOR_CONTRACT) => {}
        Some(other) => {
            return not_proven(
                "sensor",
                format!("sensor {sensor} speaks contract {other}, this core speaks {SENSOR_CONTRACT}"),
            )
        }
        None => return not_proven("sensor", format!("sensor {sensor} declared no contract version")),
    }
    if let Some(sd) = att.surface {
        if sd != surface_digest() {
            return not_proven(
                "sensor",
                format!("sensor {sensor} was built against accounting table {sd}, this core has {}", surface_digest()),
            );
        }
    } else {
        return not_proven("sensor", format!("sensor {sensor} declared no accounting table"));
    }
    // 2. A runtime whose surface nobody audited: a callable that did not exist when the table was written could
    //    be reached without the table ever saying so.
    match att.runtime {
        Some(r) if AUDITED_RUNTIMES.contains(&r) => {}
        Some(r) => {
            return not_proven(
                "runtime",
                format!("the accounting table was not audited against {r} (audited: {})", AUDITED_RUNTIMES.join(", ")),
            )
        }
        None => return not_proven("runtime", "the run named no runtime for the accounting table".into()),
    }
    // 3. Every control the table's `Controlled` answers rest on must have been on. One switched off turns a
    //    promise of "the same value in every run" into an unpinned, unrecorded read.
    for need in required_controls(sensor) {
        if !att.controls.iter().any(|c| c == need) {
            return not_proven(
                "config",
                format!(
                    "the run had the control `{need}` off, and the engine's accounting rests on it; controls on: \
                     {}",
                    if att.controls.is_empty() { "none recorded".to_string() } else { att.controls.join(", ") }
                ),
            );
        }
    }
    // 4. The channel rules that were already there. These come before the wide sensor's own findings on purpose:
    //    both answers are NOT PROVEN, but "the test started a thread" tells the reader more than
    //    "it called _thread.start_joinable_thread, which is not accounted for". The specific name wins over the
    //    generic one whenever the engine has it.
    if let Some(first) = att.marks.first() {
        return not_proven(first.split(':').next().unwrap_or(first), format!("uncontrolled source: {first}"));
    }
    // 5. What the sensor saw and could not place. This is the clause that covers channel number 27: nothing in
    //    the engine knows the name, and the verdict is NOT PROVEN all the same.
    if let Some(first) = att.unaccounted.first() {
        let kind = first.split(':').next().unwrap_or("api");
        let rest = att.unaccounted.len() - 1;
        let more = if rest > 0 { format!(" (and {rest} more)") } else { String::new() };
        return not_proven(kind, format!("not accounted for: {first}{more}"));
    }
    // 6. Something outside any test.
    if let Some(first) = att.outside.first() {
        return not_proven(
            first.split(':').next().unwrap_or("fs"),
            format!("outside any test, not accounted for: {first}"),
        );
    }
    Verdict::Provable
}

/// [`judge`] for one test of one trace, reading the attestation out of what the recorder stored.
///
/// `header` is the run's `meta.provable` object. This is what [`verify`](crate::verify) and the cache both call,
/// so there is one implementation of the rule and not three.
pub fn judge_record(
    record: &TestRecord,
    header: Option<&serde_json::Value>,
    controls: &[String],
    outside: &[String],
) -> Verdict {
    // The two evidence clauses. They come before the attestation, because a verdict can only rest on evidence
    // the record actually holds, and both of these are a record that holds none. R-058 #1 and #2.
    //
    // An empty fingerprint is what every shell writes when it has NO evidence about a test: a test that never
    // reached the runner's hooks, a test an isolate lost, a reused test whose receipt held none
    // (`node/src/vitest/shell.js`, `node/src/jest/runner.js`, `node/src/isolate.js`,
    // `node/src/cache/trace-reused.js`). Two of those compare equal -- `"" == ""` -- and the verifier used to
    // call that an identical execution. It is two absences agreeing.
    if record.fingerprint.is_empty() {
        return not_proven(
            "evidence",
            "the run recorded no fingerprint for this test: there is nothing to compare, so it cannot be shown \
             identical"
                .into(),
        );
    }
    // The record's fingerprint must be the fingerprint OF the record's own events. Nothing in the trace format
    // signs a record, `concat_traces` copies records verbatim out of parts it did not produce, and the verifier
    // reached `diff_records` only when the stored strings DIFFERED -- so when they agreed the events were never
    // read, and a record whose fingerprint does not belong to its events was reported as "observed the same
    // events". Only a complete record can be checked this way: a truncated one does not hold every event it
    // chained. `fingerprint_of` carried the doc comment "used by the verifier to validate traces" and had no
    // caller; this is that caller.
    if !record.truncated {
        let recomputed = crate::fingerprint::fingerprint_of(&record.events);
        if recomputed != record.fingerprint {
            return not_proven(
                "trace",
                format!(
                    "the record's fingerprint does not match its own events ({} event(s) recomputing to \
                     {recomputed}, stored as {}): this trace does not describe its own run",
                    record.events.len(),
                    record.fingerprint
                ),
            );
        }
    }
    let get = |k: &str| header.and_then(|h| h.get(k)).and_then(|v| v.as_str());
    let unaccounted = record.unaccounted.clone();
    let att = Attestation {
        sensor: get("sensor"),
        contract: header.and_then(|h| h.get("contract")).and_then(|v| v.as_u64()).map(|v| v as u32),
        surface: get("surface"),
        runtime: get("runtime"),
        controls,
        unaccounted: &unaccounted,
        marks: &record.uncontrolled,
        outside,
    };
    judge(&att)
}

#[cfg(test)]
mod tests {

    /// `poll` names both the poller type and its wait. Constructing a poller reads nothing; waiting for
    /// readiness is timing. The table compares the last component of a qualified name, so this pair is the
    /// place where that is not enough, and a mistake either way is a false green or a refused ordinary test.
    #[test]
    fn a_poller_may_be_built_but_its_readiness_answer_is_never_accounted() {
        assert_eq!(account("select", "poll"), Accounting::Pure);
        assert_eq!(account("select", "epoll"), Accounting::Pure);
        assert_eq!(account("select", "poll.register"), Accounting::Pure);
        assert_eq!(account("select", "poll.unregister"), Accounting::Pure);
        // the wait, under every spelling
        assert_eq!(account("select", "poll.poll"), Accounting::Unaccounted);
        assert_eq!(account("select", "epoll.poll"), Accounting::Unaccounted);
        assert_eq!(account("select", "select"), Accounting::Unaccounted);
        assert_eq!(account("selectors", "EpollSelector.select"), Accounting::Unaccounted);
    }

    /// A method of a C type is named `Type.method`, and the table compares the LAST component of a qualified
    /// name. Every arm that named a type was therefore dead code, and `os.walk` paid for it: MEASURED on this
    /// branch, a test that walked a directory was NOT PROVEN with "api:posix.DirEntry.is_dir".
    #[test]
    fn a_method_of_a_c_type_is_found_by_its_owner_and_not_by_its_last_component() {
        assert_eq!(account("posix", "DirEntry.is_dir"), Accounting::Recorded);
        assert_eq!(account("posix", "DirEntry.is_file"), Accounting::Recorded);
        assert_eq!(account("posix", "DirEntry.inode"), Accounting::Recorded);
        assert_eq!(account("posix", "ScandirIterator.__next__"), Accounting::Recorded);
        // the types themselves, the `_thread.lock` shape
        assert_eq!(account("posix", "DirEntry"), Accounting::Recorded);
        assert_eq!(account("posix", "ScandirIterator"), Accounting::Recorded);
        // a method the type table does not name is refused
        assert_eq!(account("posix", "DirEntry.invented"), Accounting::Unaccounted);
        // What the owner table does NOT do is take over the fallback: a `Type.method` whose owner it does not
        // know is still answered by the operation's own name, which is how `TextIOWrapper.readline`,
        // `socket.connect` and `Random.random` have always been answered. Inside an ENUMERATED stdlib module
        // every type is one the sensor itself reports, so this is sound there; it is written down here, and in
        // docs/CHANNELS-TO-COVER.md, because it would NOT be sound if a module outside that set were ever
        // enumerated (an unknown module is `Unaccounted` as a whole, which is what keeps it sound today).
        assert_eq!(account("posix", "SomeOtherType.read"), Accounting::Recorded);
        assert_eq!(account("_io", "TextIOWrapper.readline"), Accounting::Recorded);
    }

    /// `logging` calls `asyncio.current_task()` for every record since 3.12, so an entirely synchronous test
    /// that writes one log line was NOT PROVEN. Reporting which task is running is not scheduling; running the
    /// loop is, and that stays refused.
    #[test]
    fn asking_which_task_is_running_is_not_the_same_as_scheduling_one() {
        assert_eq!(account("_asyncio", "current_task"), Accounting::Pure);
        assert_eq!(account("_asyncio", "_get_running_loop"), Accounting::Pure);
        assert_eq!(account("_asyncio", "Task"), Accounting::Unaccounted);
        assert_eq!(account("_asyncio", "Task.__step"), Accounting::Unaccounted);
        assert_eq!(account("_asyncio", "Future"), Accounting::Unaccounted);
    }

    /// CPython 3.14's standard library registers the subinterpreter queue types on import. Registration hands
    /// the C module types it is given; a queue between interpreters carries data from outside and stays refused.
    /// MEASURED: CI 44964230574, the install leg on 3.14, "api:_interpqueues._register_heap_types" on every test.
    #[test]
    fn registering_the_subinterpreter_queue_types_is_not_using_a_queue() {
        assert_eq!(account("_interpqueues", "_register_heap_types"), Accounting::Pure);
        assert_eq!(account("_interpqueues", "put"), Accounting::Unaccounted);
        assert_eq!(account("_interpqueues", "get"), Accounting::Unaccounted);
        assert_eq!(account("_interpreters", "create"), Accounting::Unaccounted);
        assert_eq!(account("_interpchannels", "recv"), Accounting::Unaccounted);
    }
    use super::*;

    fn all_controls() -> Vec<String> {
        required_controls("py-monitoring/1").iter().map(|s| s.to_string()).collect()
    }

    fn att<'a>(unaccounted: &'a [String], marks: &'a [String], controls: &'a [String]) -> Attestation<'a> {
        Attestation {
            sensor: Some("py-monitoring/1"),
            contract: Some(SENSOR_CONTRACT),
            surface: None, // filled by the caller through `good`
            runtime: Some("cpython3.13"),
            controls,
            unaccounted,
            marks,
            outside: &[],
        }
    }

    fn good<'a>(
        unaccounted: &'a [String],
        marks: &'a [String],
        surface: &'a str,
        controls: &'a [String],
    ) -> Attestation<'a> {
        Attestation { surface: Some(surface), ..att(unaccounted, marks, controls) }
    }

    #[test]
    fn a_clean_run_with_a_known_sensor_is_provable() {
        let s = surface_digest();
        let c = all_controls();
        assert_eq!(judge(&good(&[], &[], &s, &c)), Verdict::Provable);
    }

    #[test]
    fn no_sensor_is_not_proven() {
        // the whole point: a trace that says nothing about what it watched cannot be called identical
        let a = Attestation { sensor: None, ..Default::default() };
        match judge(&a) {
            Verdict::NotProven { kind, .. } => assert_eq!(kind, "sensor"),
            v => panic!("expected NotProven, got {v:?}"),
        }
    }

    #[test]
    fn an_unknown_contract_or_table_is_not_proven() {
        let s = surface_digest();
        let c = all_controls();
        let a = Attestation { contract: Some(SENSOR_CONTRACT + 1), ..good(&[], &[], &s, &c) };
        assert!(!judge(&a).is_provable());
        let a = Attestation { surface: Some("deadbeef"), ..att(&[], &[], &c) };
        assert!(!judge(&a).is_provable());
        let a = Attestation { surface: None, ..att(&[], &[], &c) };
        assert!(!judge(&a).is_provable());
    }

    #[test]
    fn an_unaudited_runtime_is_not_proven() {
        let s = surface_digest();
        let c = all_controls();
        let a = Attestation { runtime: Some("cpython3.99"), ..good(&[], &[], &s, &c) };
        match judge(&a) {
            Verdict::NotProven { kind, .. } => assert_eq!(kind, "runtime"),
            v => panic!("expected NotProven, got {v:?}"),
        }
        let a = Attestation { runtime: None, ..good(&[], &[], &s, &c) };
        assert!(!judge(&a).is_provable());
    }

    #[test]
    fn a_control_the_accounting_rests_on_being_off_is_not_proven() {
        // every `Controlled` answer is a promise kept by a control the user can switch off. With it off there is
        // no patch, so no pinned value and no event -- and a table that still said `Controlled` would be a false
        // IDENTICAL.
        let s = surface_digest();
        let full = all_controls();
        for drop in required_controls("py-monitoring/1") {
            let c: Vec<String> = full.iter().filter(|x| x.as_str() != *drop).cloned().collect();
            match judge(&good(&[], &[], &s, &c)) {
                Verdict::NotProven { kind, detail } => {
                    assert_eq!(kind, "config", "dropping {drop}: {detail}");
                    assert!(detail.contains(drop), "dropping {drop} is not named: {detail}");
                }
                v => panic!("dropping the control {drop} still gave {v:?}"),
            }
        }
        // and with every one of them on, the run is provable again
        assert_eq!(judge(&good(&[], &[], &s, &full)), Verdict::Provable);
        // a run that records no controls at all cannot be identical either
        assert!(!judge(&good(&[], &[], &s, &[])).is_provable());
    }

    #[test]
    fn the_two_shells_rest_on_different_controls() {
        assert!(required_controls("py-monitoring/1").contains(&"os"));
        assert!(required_controls("py-monitoring/1").contains(&"hashseed"));
        // Node pins the host name and the CPU count unconditionally, so it needs no `env` control for them
        assert!(!required_controls("node-surface/1").contains(&"env"));
        assert!(required_controls("node-surface/1").contains(&"timers"));
        // R-058 #4: this assertion used to read `is_empty()`, which is what made clause 3 fail OPEN for a
        // sensor the core has no rule for -- the bug and its test agreed with each other. A name outside the
        // known set is refused by `judge` on the name alone, and the list it would have iterated asks for
        // every control both shells rest on, so even reaching it is a refusal.
        assert!(!sensor_known("something-else/9"));
        assert!(!required_controls("something-else/9").is_empty());
        assert!(sensor_known("py-monitoring/1") && sensor_known("node-surface/1"));
        assert!(sensor_known(SENSOR_CACHE_REUSE));
    }

    #[test]
    fn a_sensor_this_core_has_no_rule_for_is_not_proven() {
        // The whole of R-058 #4, at the predicate: a run whose header is otherwise perfect -- this core's
        // contract, this core's table, an audited runtime, every control on -- is still NOT PROVEN when the
        // sensor is one the accounting table was not written against.
        let s = surface_digest();
        let c = all_controls();
        for sensor in ["cache-reuse/2", "totally-made-up/9", "x", "py", "node", "deno-whatever/1"] {
            let a = Attestation { sensor: Some(sensor), ..good(&[], &[], &s, &c) };
            match judge(&a) {
                Verdict::NotProven { kind, .. } => assert_eq!(kind, "sensor", "sensor {sensor}"),
                v => panic!("sensor {sensor}: expected NotProven, got {v:?}"),
            }
        }
    }

    #[test]
    fn anything_the_sensor_could_not_place_is_not_proven() {
        let s = surface_digest();
        let c = all_controls();
        let u = vec!["api:posix.getxattr".to_string()];
        match judge(&good(&u, &[], &s, &c)) {
            Verdict::NotProven { kind, detail } => {
                assert_eq!(kind, "api");
                assert!(detail.contains("posix.getxattr"), "{detail}");
            }
            v => panic!("expected NotProven, got {v:?}"),
        }
        let u = vec!["native:lxml.etree".to_string(), "api:x.y".to_string()];
        match judge(&good(&u, &[], &s, &c)) {
            Verdict::NotProven { kind, detail } => {
                assert_eq!(kind, "native");
                assert!(detail.contains("and 1 more"), "{detail}");
            }
            v => panic!("expected NotProven, got {v:?}"),
        }
    }

    #[test]
    fn the_older_channel_marks_still_decide() {
        let s = surface_digest();
        let c = all_controls();
        let m = vec!["thread".to_string()];
        match judge(&good(&[], &m, &s, &c)) {
            Verdict::NotProven { kind, .. } => assert_eq!(kind, "thread"),
            v => panic!("expected NotProven, got {v:?}"),
        }
    }

    #[test]
    fn a_named_channel_is_reported_before_the_sensors_generic_finding() {
        // a test that starts a thread also calls _thread.start_joinable_thread, which the table does not account
        // for. Both answers are NOT PROVEN; the report must say "thread", which tells the reader what happened.
        let s = surface_digest();
        let c = all_controls();
        let u = vec!["api:_thread.start_joinable_thread".to_string()];
        let m = vec!["thread".to_string()];
        match judge(&good(&u, &m, &s, &c)) {
            Verdict::NotProven { kind, detail } => {
                assert_eq!(kind, "thread", "{detail}");
                assert!(detail.contains("thread"), "{detail}");
            }
            v => panic!("expected NotProven, got {v:?}"),
        }
        // with no mark, the sensor's own finding is the answer: the general rule still bites
        match judge(&good(&u, &[], &s, &c)) {
            Verdict::NotProven { kind, detail } => {
                assert_eq!(kind, "api");
                assert!(detail.contains("_thread.start_joinable_thread"), "{detail}");
            }
            v => panic!("expected NotProven, got {v:?}"),
        }
    }

    #[test]
    fn something_outside_any_test_is_not_proven() {
        let s = surface_digest();
        let c = all_controls();
        let outside = vec!["env:TMPDIR".to_string()];
        let a = Attestation { outside: &outside, ..good(&[], &[], &s, &c) };
        match judge(&a) {
            Verdict::NotProven { kind, .. } => assert_eq!(kind, "env"),
            v => panic!("expected NotProven, got {v:?}"),
        }
    }

    // ---- the accounting table -------------------------------------------------------------------

    #[test]
    fn an_unlisted_name_is_unaccounted_not_pure() {
        // the property the whole design rests on: the table's default answer is "I do not know"
        assert_eq!(account("posix", "getxattr"), Accounting::Unaccounted);
        assert_eq!(account("posix", "listxattr"), Accounting::Unaccounted);
        assert_eq!(account("time", "clock_gettime_coarse"), Accounting::Unaccounted);
        assert_eq!(account("sys", "settrace"), Accounting::Unaccounted);
        assert_eq!(account("gc", "get_objects"), Accounting::Unaccounted);
        assert_eq!(account("pwd", "getpwuid"), Accounting::Unaccounted);
    }

    #[test]
    fn a_module_nobody_wrote_a_rule_for_is_unaccounted() {
        // channel number 27: a module that did not exist when this table was written
        assert_eq!(account("_someextension", "anything"), Accounting::Unaccounted);
        assert_eq!(account("ctypes", "CDLL"), Accounting::Unaccounted);
        assert_eq!(account("", "anonymous"), Accounting::Unaccounted);
    }

    #[test]
    fn the_channels_the_engine_does_account_for() {
        assert_eq!(account("builtins", "open"), Accounting::Recorded);
        assert_eq!(account("posix", "stat"), Accounting::Recorded);
        assert_eq!(account("posix", "listdir"), Accounting::Recorded);
        assert_eq!(account("posix", "urandom"), Accounting::Controlled);
        assert_eq!(account("posix", "uname"), Accounting::Input);
        assert_eq!(account("time", "time"), Accounting::Controlled);
        assert_eq!(account("time", "process_time"), Accounting::Recorded);
        assert_eq!(account("_socket", "gethostname"), Accounting::Controlled);
        assert_eq!(account("_socket", "connect"), Accounting::Recorded);
        assert_eq!(account("_random", "random"), Accounting::Controlled);
        assert_eq!(account("resource", "getrusage"), Accounting::Recorded);
        assert_eq!(account("_imp", "create_dynamic"), Accounting::Input);
        assert_eq!(account("builtins", "id"), Accounting::Controlled);
    }

    #[test]
    fn the_pure_surface_needs_no_entry_of_its_own() {
        // what the measurement found tests actually spend their calls on
        for q in ["isinstance", "list.append", "dict.get", "len", "getattr", "str.encode", "print", "compile"] {
            assert_eq!(account("builtins", q), Accounting::Pure, "builtins.{q}");
        }
        for m in ["math", "itertools", "_json", "binascii", "zlib", "_struct", "_heapq", "_pickle", "_sre"] {
            assert_eq!(account(m, "anything"), Accounting::Pure, "{m}");
        }
    }

    #[test]
    fn a_pure_module_can_still_have_a_clock_in_it() {
        assert_eq!(account("datetime", "datetime.now"), Accounting::Controlled);
        assert_eq!(account("datetime", "timedelta.__add__"), Accounting::Pure);
    }

    #[test]
    fn the_runner_and_the_engine_are_the_declared_controlled_set() {
        assert_eq!(account("detpy._level0", "anything"), Accounting::Controlled);
        assert_eq!(account("_pytest.capture", "EncodedFile.read"), Accounting::Controlled);
        assert_eq!(account("pluggy._hooks", "call"), Accounting::Controlled);
        // a module that merely starts with the same letters is not infrastructure
        assert_eq!(account("detpyish", "x"), Accounting::Unaccounted);
    }

    #[test]
    fn a_native_extension_is_controlled_only_when_it_was_audited() {
        assert!(CONTROLLED_NATIVE.contains(&"detpy._core"));
        assert!(!CONTROLLED_NATIVE.contains(&"lxml.etree"));
    }

    #[test]
    fn the_surface_digest_is_stable_and_covers_the_arms() {
        assert_eq!(surface_digest(), surface_digest());
        assert_eq!(surface_digest().len(), 32);
        // every probe name resolves through the public entry point
        for (m, q) in PROBE_NAMES {
            let _ = account(m, q);
        }
    }

    // ---- the Node half -------------------------------------------------------------------------

    #[test]
    fn a_node_module_or_export_the_table_does_not_know_is_unaccounted() {
        // channel 27 on the Node side: a builtin nobody wrote a rule for, and an export nobody listed
        assert_eq!(account_node("sqlite", "DatabaseSync"), Accounting::Unaccounted);
        assert_eq!(account_node("inspector", "open"), Accounting::Unaccounted);
        assert_eq!(account_node("v8", "getHeapStatistics"), Accounting::Unaccounted);
        // a value of this process turned into bytes and back is not a channel; the heap is
        assert_eq!(account_node("v8", "serialize"), Accounting::Pure);
        // the loader's synchronous port read is the module's own source, which is a run input; a worker of the
        // test's own is refused where it is created
        assert_eq!(account_node("worker_threads", "receiveMessageOnPort"), Accounting::Input);
        assert_eq!(account_node("worker_threads", "Worker"), Accounting::Unaccounted);
        assert_eq!(account_node("worker_threads", "parentPort"), Accounting::Unaccounted);
        assert_eq!(account_node("worker_threads", "MessageChannel"), Accounting::Unaccounted);
        assert_eq!(account_node("v8", "deserialize"), Accounting::Pure);
        assert_eq!(account_node("os", "somethingNodeAddsIn2027"), Accounting::Unaccounted);
        assert_eq!(account_node("a_module_that_does_not_exist", "x"), Accounting::Unaccounted);
        assert_eq!(account_node("fs", "watch"), Accounting::Unaccounted);
        // loading an addon is recorded (its path and digest are a run input) and the native rule decides
        // whether its C code is reasoned about, so the refusal is made there and not by this name
        assert_eq!(account_node("process", "dlopen"), Accounting::Recorded);
        assert_eq!(account_node("process", "stdin"), Accounting::Unaccounted);
        assert_eq!(account_node("perf_hooks", "monitorEventLoopDelay"), Accounting::Unaccounted);
    }

    #[test]
    fn the_node_channels_the_engine_does_account_for() {
        assert_eq!(account_node("os", "hostname"), Accounting::Recorded);
        assert_eq!(account_node("fs", "readFileSync"), Accounting::Recorded);
        assert_eq!(account_node("fs", "writeFileSync"), Accounting::Pure);
        assert_eq!(account_node("net", "connect"), Accounting::Recorded);
        assert_eq!(account_node("dns", "lookup"), Accounting::Recorded);
        assert_eq!(account_node("crypto", "randomBytes"), Accounting::Controlled);
        assert_eq!(account_node("crypto", "createHash"), Accounting::Pure);
        assert_eq!(account_node("process", "env"), Accounting::Recorded);
        assert_eq!(account_node("process", "hrtime"), Accounting::Controlled);
        assert_eq!(account_node("process", "argv"), Accounting::Input);
        assert_eq!(account_node("timers", "setTimeout"), Accounting::Controlled);
        assert_eq!(account_node("worker_threads", "threadId"), Accounting::Controlled);
        // a thread and a child process stay refused, as the older marks already said
        assert_eq!(account_node("worker_threads", "Worker"), Accounting::Unaccounted);
        assert_eq!(account_node("child_process", "spawn"), Accounting::Unaccounted);
    }

    #[test]
    fn the_node_pure_modules_need_no_entry() {
        for m in ["path", "url", "querystring", "buffer", "events", "stream", "util", "assert", "zlib"] {
            assert_eq!(account_node(m, "anything"), Accounting::Pure, "{m}");
        }
        // the `node:` prefix is accepted on either form
        assert_eq!(account_node("node:path", "join"), Accounting::Pure);
        assert_eq!(account_node("node:os", "hostname"), Accounting::Recorded);
    }

    #[test]
    fn accounted_is_everything_but_unaccounted() {
        for a in [Accounting::Pure, Accounting::Controlled, Accounting::Recorded, Accounting::Input] {
            assert!(a.is_accounted(), "{a:?}");
        }
        assert!(!Accounting::Unaccounted.is_accounted());
    }
}
