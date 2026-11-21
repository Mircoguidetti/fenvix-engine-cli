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

/// Native extension modules whose own C code the engine has reasoned about.
///
/// A test that loads any other extension module is NOT PROVEN: its C code could read a file or the real clock
/// without emitting anything a sensor can see (the declared residual). The list is deliberately short; it grows
/// only by someone auditing an extension and saying so here.
pub const CONTROLLED_NATIVE: &[&str] = &[
    // the engine's own extension and the accelerators of the pure modules above
    "detpy._core",
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
        "posix" | "os" | "nt" => posix_account(name),
        "time" => time_account(name),
        "_io" | "io" => io_account(name),
        "_socket" | "socket" => socket_account(name),
        "_thread" | "threading" => thread_account(name),
        "_random" | "random" => random_account(name),
        "select" | "_selectors" | "selectors" => Accounting::Unaccounted, // I/O readiness: uncontrolled.io
        "_sqlite3" | "sqlite3" => sqlite_account(name),
        "sys" => sys_account(name),
        "gc" => gc_account(name),
        "resource" => resource_account(name),
        "_imp" | "_frozen_importlib" | "_frozen_importlib_external" | "importlib" | "marshal" | "zipimport" => {
            import_account(name)
        }
        "_warnings" | "atexit" | "_tracemalloc" | "faulthandler" => Accounting::Pure,
        // the C tokenizer and the AST builder read source text they are handed, nothing else
        "_tokenize" => Accounting::Pure,
        "_ssl" => ssl_account(name),
        "fcntl" | "termios" | "mmap" | "signal" | "_posixsubprocess" | "_multiprocessing" | "_curses" | "pwd"
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
        "_warnings", "atexit", "_tracemalloc", "faulthandler", "_tokenize", "_ssl", "fcntl", "termios", "mmap",
        "signal",
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
        // reads the standard input, which no event carries
        "input" => Accounting::Unaccounted,
        // `vars`, `dir`, `globals`, `locals`, `compile`, `exec`, `eval`, `print`, `repr`, and every container,
        // text and number operation: a function of what is already in the process
        _ => {
            // a method of a C type reached through builtins (`builtins.list.append`, `builtins.str.encode`)
            let _ = qualname;
            Accounting::Pure
        }
    }
}

fn posix_account(name: &str) -> Accounting {
    match name {
        // file metadata: an `fs.stat` event (`<path>|<type>`, with size and mtime when the call returns them)
        "stat" | "lstat" | "fstat" | "fstatat" | "access" | "readlink" | "statvfs" | "fstatvfs" => {
            Accounting::Recorded
        }
        // directory enumeration: the order is normalised and recorded
        "listdir" | "scandir" => Accounting::Recorded,
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
        // a child process: `uncontrolled.child`, which is already NOT PROVEN
        "fork" | "forkpty" | "_exit" | "abort" | "system" | "popen" | "spawnv" | "spawnve" | "spawnvp"
        | "spawnvpe" | "posix_spawn" | "posix_spawnp" | "execv" | "execve" | "execvp" | "execvpe" | "wait"
        | "wait3" | "wait4" | "waitpid" | "waitid" | "kill" | "killpg" => Accounting::Unaccounted,
        // writes and pure path work: a write carries no information into the test
        "write" | "pwrite" | "writev" | "pwritev" | "close" | "closerange" | "fsync" | "fdatasync" | "ftruncate"
        | "truncate" | "lseek" | "dup" | "dup2" | "pipe" | "pipe2" | "mkdir" | "makedirs" | "rmdir" | "remove"
        | "unlink" | "rename" | "replace" | "link" | "symlink" | "chmod" | "chown" | "lchown" | "fchmod"
        | "fchown" | "utime" | "mkfifo" | "mknod" | "device_encoding" | "set_inheritable"
        | "get_inheritable" | "set_blocking" | "get_blocking" | "fspath" | "strerror" | "isatty" => {
            Accounting::Pure
        }
        // the working directory: pinned to the project root by `--det`
        "getcwd" | "getcwdb" | "chdir" | "fchdir" => Accounting::Controlled,
        // string work on paths, no call to the operating system at all
        "_path_normpath" | "_path_splitroot_ex" | "_path_isabs" | "_path_join" | "_path_split"
        | "_path_splitext" | "_path_islink" => Accounting::Pure,
        // the entries `scandir` hands out: part of the recorded enumeration, and their metadata is `fs.stat`
        "DirEntry.is_dir" | "DirEntry.is_file" | "DirEntry.is_symlink" | "DirEntry.is_junction"
        | "DirEntry.stat" | "DirEntry.inode" | "DirEntry.__fspath__" | "ScandirIterator.__next__"
        | "ScandirIterator.close" => Accounting::Recorded,
        // the result tuple types of `uname` and `stat`: carriers, pinned with the input they come from
        "uname_result" | "stat_result" | "statvfs_result" | "terminal_size" | "times_result"
        | "waitid_result" | "sched_param" => Accounting::Input,
        // extended attributes, resource limits, scheduling, the user database, terminal size: no event today
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
        "get_clock_info" => Accounting::Pure,
        _ => Accounting::Unaccounted,
    }
}

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
        // locks and thread-local storage carry no outside information; the identifier is pinned
        "allocate_lock" | "RLock" | "LockType" | "acquire" | "release" | "locked" | "__enter__" | "__exit__"
        | "get_ident" | "get_native_id" | "stack_size" | "_count" | "_local" | "TIMEOUT_MAX" | "daemon_threads_allowed" => {
            Accounting::Controlled
        }
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

/// Digest of everything this table claims, so a shell cannot be built against one version of it and judged
/// against another. The shell writes the value it was built with into the trace header; [`judge`] refuses a trace
/// whose digest is not this one.
pub fn surface_digest() -> String {
    let mut buf = Vec::new();
    buf.extend_from_slice(&SENSOR_CONTRACT.to_le_bytes());
    for part in [AUDITED_RUNTIMES, PURE_MODULES, INFRA_PREFIXES, CONTROLLED_NATIVE] {
        buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
        for s in part {
            buf.extend_from_slice(s.as_bytes());
            buf.push(0);
        }
    }
    // the per-name arms, probed through the public entry point so the digest follows any change to them
    for (m, q) in PROBE_NAMES {
        buf.extend_from_slice(m.as_bytes());
        buf.push(b'.');
        buf.extend_from_slice(q.as_bytes());
        buf.push(b'=');
        buf.extend_from_slice(account(m, q).as_str().as_bytes());
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
/// a runtime the table was audited against; did the sensor see anything it could not place; is there an older
/// channel mark; did something happen outside the tests. The first clause that fails is the answer, so the report
/// names the most fundamental gap rather than a symptom of it.
pub fn judge(att: &Attestation<'_>) -> Verdict {
    // 1. No sensor, or one built against a different table: the core will not guess what was looked at.
    let Some(sensor) = att.sensor.filter(|s| !s.is_empty()) else {
        return not_proven(
            "sensor",
            "the run declared no sensor: nothing shows what the test did, so it cannot be shown identical".into(),
        );
    };
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
    // 3. What the sensor saw and could not place. This is the clause that covers channel number 27.
    if let Some(first) = att.unaccounted.first() {
        let kind = first.split(':').next().unwrap_or("api");
        let rest = att.unaccounted.len() - 1;
        let more = if rest > 0 { format!(" (and {rest} more)") } else { String::new() };
        return not_proven(kind, format!("not accounted for: {first}{more}"));
    }
    // 4. The channel rules that were already there.
    if let Some(first) = att.marks.first() {
        return not_proven(first.split(':').next().unwrap_or(first), format!("uncontrolled source: {first}"));
    }
    // 5. Something outside any test.
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
pub fn judge_record(record: &TestRecord, header: Option<&serde_json::Value>, outside: &[String]) -> Verdict {
    let get = |k: &str| header.and_then(|h| h.get(k)).and_then(|v| v.as_str());
    let unaccounted = record.unaccounted.clone();
    let att = Attestation {
        sensor: get("sensor"),
        contract: header.and_then(|h| h.get("contract")).and_then(|v| v.as_u64()).map(|v| v as u32),
        surface: get("surface"),
        runtime: get("runtime"),
        unaccounted: &unaccounted,
        marks: &record.uncontrolled,
        outside,
    };
    judge(&att)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn att<'a>(unaccounted: &'a [String], marks: &'a [String]) -> Attestation<'a> {
        Attestation {
            sensor: Some("py-monitoring/1"),
            contract: Some(SENSOR_CONTRACT),
            surface: None, // filled by the caller through `with_surface`
            runtime: Some("cpython3.13"),
            unaccounted,
            marks,
            outside: &[],
        }
    }

    fn good<'a>(unaccounted: &'a [String], marks: &'a [String], surface: &'a str) -> Attestation<'a> {
        Attestation { surface: Some(surface), ..att(unaccounted, marks) }
    }

    #[test]
    fn a_clean_run_with_a_known_sensor_is_provable() {
        let s = surface_digest();
        assert_eq!(judge(&good(&[], &[], &s)), Verdict::Provable);
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
        let a = Attestation { contract: Some(SENSOR_CONTRACT + 1), ..good(&[], &[], &s) };
        assert!(!judge(&a).is_provable());
        let a = Attestation { surface: Some("deadbeef"), ..att(&[], &[]) };
        assert!(!judge(&a).is_provable());
        let a = Attestation { surface: None, ..att(&[], &[]) };
        assert!(!judge(&a).is_provable());
    }

    #[test]
    fn an_unaudited_runtime_is_not_proven() {
        let s = surface_digest();
        let a = Attestation { runtime: Some("cpython3.99"), ..good(&[], &[], &s) };
        match judge(&a) {
            Verdict::NotProven { kind, .. } => assert_eq!(kind, "runtime"),
            v => panic!("expected NotProven, got {v:?}"),
        }
        let a = Attestation { runtime: None, ..good(&[], &[], &s) };
        assert!(!judge(&a).is_provable());
    }

    #[test]
    fn anything_the_sensor_could_not_place_is_not_proven() {
        let s = surface_digest();
        let u = vec!["api:posix.getxattr".to_string()];
        match judge(&good(&u, &[], &s)) {
            Verdict::NotProven { kind, detail } => {
                assert_eq!(kind, "api");
                assert!(detail.contains("posix.getxattr"), "{detail}");
            }
            v => panic!("expected NotProven, got {v:?}"),
        }
        let u = vec!["native:lxml.etree".to_string(), "api:x.y".to_string()];
        match judge(&good(&u, &[], &s)) {
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
        let m = vec!["thread".to_string()];
        match judge(&good(&[], &m, &s)) {
            Verdict::NotProven { kind, .. } => assert_eq!(kind, "thread"),
            v => panic!("expected NotProven, got {v:?}"),
        }
    }

    #[test]
    fn something_outside_any_test_is_not_proven() {
        let s = surface_digest();
        let outside = vec!["env:TMPDIR".to_string()];
        let a = Attestation { outside: &outside, ..good(&[], &[], &s) };
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

    #[test]
    fn accounted_is_everything_but_unaccounted() {
        for a in [Accounting::Pure, Accounting::Controlled, Accounting::Recorded, Accounting::Input] {
            assert!(a.is_accounted(), "{a:?}");
        }
        assert!(!Accounting::Unaccounted.is_accounted());
    }
}
