//! What the engine observes about its own process on each supported OS (Linux, macOS), in one place.
//!
//! The Python and Node shells used to read `/proc` directly; on macOS those reads fail and returned "nothing",
//! so a library loaded at run time or a native-code dependency was not an input of the test there (audit G-0155,
//! G-0156, G-0157). Every function here either answers on the OS it runs on or returns `None`: the caller then
//! makes the unknown part of the key or refuses reuse, never reads "nothing" as "no input".

/// Paths of the shared objects mapped into this process (each once, in load order): `/proc/self/maps` on Linux,
/// the dyld image list on macOS. `None` where neither exists.
pub fn loaded_images() -> Option<Vec<String>> {
    imp::loaded_images()
}

/// A digest-ready description of the CPU's instruction-set features where `/proc/cpuinfo` does not exist
/// (macOS: the CPU brand and the `hw.optional` feature flags native code dispatches on). `None` elsewhere.
pub fn cpu_features() -> Option<String> {
    imp::cpu_features()
}

/// Whether this process has live child processes; `None` when the OS gives no way to know.
pub fn children_alive() -> Option<bool> {
    imp::children_alive()
}

/// Whether `name` (a file name) is a shared library on this OS (`*.so`, `*.so.N` on Linux; `*.dylib` and
/// `*.so` bundles on macOS).
pub fn is_shared_library_name(name: &str) -> bool {
    name.ends_with(".so") || name.contains(".so.") || name.ends_with(".dylib")
}

fn dedup(paths: impl IntoIterator<Item = String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    paths.into_iter().filter(|p| seen.insert(p.clone())).collect()
}

/// The paths of a `/proc/<pid>/maps` text (the field after the inode, when it is an absolute path).
pub fn maps_paths(text: &str) -> Vec<String> {
    dedup(text.lines().filter_map(|l| l.find('/').map(|i| l[i..].trim_end().to_string())))
}

#[cfg(target_os = "linux")]
mod imp {
    pub fn loaded_images() -> Option<Vec<String>> {
        let text = std::fs::read_to_string("/proc/self/maps").ok()?;
        Some(super::maps_paths(&text))
    }

    pub fn cpu_features() -> Option<String> {
        None
    }

    pub fn children_alive() -> Option<bool> {
        let rd = std::fs::read_dir("/proc/self/task").ok()?;
        for e in rd.flatten() {
            if let Ok(s) = std::fs::read_to_string(e.path().join("children")) {
                if !s.trim().is_empty() {
                    return Some(true);
                }
            }
        }
        Some(false)
    }
}

#[cfg(target_os = "macos")]
mod imp {
    use std::ffi::{c_char, c_int, c_void, CStr, CString};

    extern "C" {
        fn _dyld_image_count() -> u32;
        fn _dyld_get_image_name(image_index: u32) -> *const c_char;
        fn sysctlbyname(name: *const c_char, oldp: *mut c_void, oldlenp: *mut usize, newp: *mut c_void, newlen: usize) -> c_int;
        fn proc_listchildpids(ppid: c_int, buffer: *mut c_void, buffersize: c_int) -> c_int;
        fn getpid() -> c_int;
    }

    pub fn loaded_images() -> Option<Vec<String>> {
        let n = unsafe { _dyld_image_count() };
        let mut out = Vec::with_capacity(n as usize);
        for i in 0..n {
            let p = unsafe { _dyld_get_image_name(i) };
            if p.is_null() {
                continue;
            }
            out.push(unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned());
        }
        Some(super::dedup(out))
    }

    fn sysctl_bytes(name: &str) -> Option<Vec<u8>> {
        let c = CString::new(name).ok()?;
        let mut len: usize = 0;
        if unsafe { sysctlbyname(c.as_ptr(), std::ptr::null_mut(), &mut len, std::ptr::null_mut(), 0) } != 0 {
            return None;
        }
        let mut buf = vec![0u8; len];
        if unsafe { sysctlbyname(c.as_ptr(), buf.as_mut_ptr().cast(), &mut len, std::ptr::null_mut(), 0) } != 0 {
            return None;
        }
        buf.truncate(len);
        Some(buf)
    }

    /// Feature flags of Apple silicon (and the x86 ones Rosetta reports) that compilers and math libraries
    /// dispatch on; a flag absent on this OS version is recorded as absent.
    const FEATURES: &[&str] = &[
        "hw.optional.arm.FEAT_FP16", "hw.optional.arm.FEAT_DotProd", "hw.optional.arm.FEAT_BF16",
        "hw.optional.arm.FEAT_I8MM", "hw.optional.arm.FEAT_FHM", "hw.optional.arm.FEAT_RDM",
        "hw.optional.arm.FEAT_FCMA", "hw.optional.arm.FEAT_JSCVT", "hw.optional.arm.FEAT_LSE",
        "hw.optional.arm.FEAT_LSE2", "hw.optional.arm.FEAT_SHA3", "hw.optional.arm.FEAT_SHA512",
        "hw.optional.arm.FEAT_SME", "hw.optional.arm.FEAT_SME2", "hw.optional.arm.FEAT_SVE",
        "hw.optional.arm.FEAT_FRINTTS", "hw.optional.arm.FEAT_AFP", "hw.optional.AdvSIMD",
        "hw.optional.avx1_0", "hw.optional.avx2_0", "hw.optional.avx512f",
    ];

    pub fn cpu_features() -> Option<String> {
        let brand = sysctl_bytes("machdep.cpu.brand_string")?;
        let brand = String::from_utf8_lossy(&brand).trim_end_matches('\0').to_string();
        let mut out = vec![format!("brand={brand}")];
        for f in FEATURES {
            let v = match sysctl_bytes(f) {
                Some(b) if b.len() >= 4 => i32::from_ne_bytes([b[0], b[1], b[2], b[3]]).to_string(),
                Some(_) => "?".to_string(),
                None => "-".to_string(),
            };
            out.push(format!("{f}={v}"));
        }
        Some(out.join(" "))
    }

    pub fn children_alive() -> Option<bool> {
        let mut buf = [0 as c_int; 64];
        let n = unsafe {
            proc_listchildpids(getpid(), buf.as_mut_ptr().cast(), (buf.len() * std::mem::size_of::<c_int>()) as c_int)
        };
        if n < 0 {
            return None;
        }
        Some(n > 0)
    }
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
mod imp {
    pub fn loaded_images() -> Option<Vec<String>> {
        None
    }
    pub fn cpu_features() -> Option<String> {
        None
    }
    pub fn children_alive() -> Option<bool> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_paths_takes_absolute_paths_once() {
        let t = "7f00-7f01 r-xp 0 08:01 1 /usr/lib/libc.so.6\n7f01-7f02 r--p 0 08:01 1 /usr/lib/libc.so.6\n\
                 7f02-7f03 rw-p 0 00:00 0 [heap]\n7f03-7f04 r-xp 0 08:01 2 /opt/x y/libz.so.1 (deleted)\n";
        assert_eq!(maps_paths(t), vec!["/usr/lib/libc.so.6", "/opt/x y/libz.so.1 (deleted)"]);
    }

    #[test]
    fn loaded_images_sees_this_process_libc_on_supported_os() {
        let imgs = loaded_images();
        if cfg!(any(target_os = "linux", target_os = "macos")) {
            let imgs = imgs.expect("the loaded-image list must be available on Linux and macOS");
            assert!(imgs.iter().any(|p| p.contains("libc") || p.contains("libSystem")), "{imgs:?}");
        }
    }

    #[test]
    fn children_alive_is_known_on_supported_os() {
        if cfg!(any(target_os = "linux", target_os = "macos")) {
            assert_eq!(children_alive(), Some(false));
            let mut c = std::process::Command::new("sleep").arg("2").spawn().unwrap();
            assert_eq!(children_alive(), Some(true));
            c.kill().ok();
            c.wait().ok();
        }
    }

    #[test]
    fn cpu_features_present_on_macos() {
        if cfg!(target_os = "macos") {
            assert!(cpu_features().expect("sysctl").starts_with("brand="));
        }
    }

    #[test]
    fn library_names() {
        assert!(is_shared_library_name("libssl.3.dylib"));
        assert!(is_shared_library_name("libc.so.6"));
        assert!(!is_shared_library_name("python3.13"));
    }
}
