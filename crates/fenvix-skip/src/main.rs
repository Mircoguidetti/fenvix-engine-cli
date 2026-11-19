//! `fenvix-skip decide A_DEPS_DIR B_DEPS_DIR --root-b DIR [--json OUT]`
//!
//! Prints one line per test of A (REUSE or RUN with the reason); with --json, writes the rows
//! (module, id, reusable, reason, outcome_a, outcome_b, ms_b) as a JSON array ("-" = stdout only).
use std::path::PathBuf;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) != Some("decide") || args.len() < 3 {
        eprintln!("usage: fenvix-skip decide A_DEPS_DIR B_DEPS_DIR --root-b DIR [--json OUT]");
        std::process::exit(2);
    }
    let a = PathBuf::from(&args[1]);
    let b = PathBuf::from(&args[2]);
    let mut root_b = None;
    let mut json = None;
    let mut i = 3;
    while i < args.len() {
        match args[i].as_str() {
            "--root-b" => {
                root_b = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--json" => {
                json = args.get(i + 1).cloned();
                i += 2;
            }
            other => {
                eprintln!("unknown argument {}", other);
                std::process::exit(2);
            }
        }
    }
    let root_b = root_b.unwrap_or_else(|| {
        eprintln!("--root-b is required");
        std::process::exit(2);
    });
    let rows = match fenvix_skip::decide_dirs(&a, &b, &root_b) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("fenvix-skip: {}", e);
            std::process::exit(1);
        }
    };
    match json.as_deref() {
        Some("-") => println!("{}", serde_json::Value::Array(rows)),
        Some(path) => {
            std::fs::write(path, serde_json::to_string(&rows).unwrap()).unwrap_or_else(|e| {
                eprintln!("fenvix-skip: {}: {}", path, e);
                std::process::exit(1);
            });
            print_rows(&rows);
        }
        None => print_rows(&rows),
    }
}

fn print_rows(rows: &[serde_json::Value]) {
    for r in rows {
        let m = r["module"].as_str().unwrap_or("");
        let id = r["id"].as_str().unwrap_or("");
        if r["reusable"].as_bool().unwrap_or(false) {
            println!("REUSE {}::{}", m, id);
        } else {
            let rs = &r["reason"];
            println!("RUN   {}::{}  [{}: {}]", m, id, rs[0].as_str().unwrap_or(""), rs[1].as_str().unwrap_or(""));
        }
    }
}
