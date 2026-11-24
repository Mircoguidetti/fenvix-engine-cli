//! P0 big trace, criterion 6: the bounded-memory verifier gives the report of the verifier it replaced.
//!
//! tests/golden/ holds every case `verify::tests::golden_corpus_generate` wrote at f67be4a3, BEFORE the record-source
//! refactor (first commit of the branch): the runs of each case (`<case>.runN.jsonl`) and the report the unmodified
//! code gave (`<case>.report.json`, labels set to run0, run1, ...).
//!
//! protects=the verify report (every verdict, divergence, summary count, input difference) over in-memory traces
//! (`verify`, MemTrace) and over files (`verify_paths` / `verify_paths_ignoring`, FileTrace) is byte for byte the
//! pre-refactor report; fails_when=the slim records, the on-demand loading or the env/uncontrolled summaries change
//! any field of any report in the corpus; no_claim=reports for traces outside the corpus, or memory use (measured
//! separately on the agentic-qe pair, harness/p0_big_trace/REPORT.md).

use detpy_core::trace::read_trace;
use detpy_core::verify::{verify, verify_paths, verify_paths_ignoring, Report};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn golden() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("golden")
}

/// case -> its run files in order
fn cases() -> BTreeMap<String, Vec<PathBuf>> {
    let mut out: BTreeMap<String, Vec<PathBuf>> = BTreeMap::new();
    for e in std::fs::read_dir(golden()).unwrap() {
        let p = e.unwrap().path();
        let name = p.file_name().unwrap().to_string_lossy().to_string();
        if let Some(case) = name.strip_suffix(".report.json") {
            let mut runs = Vec::new();
            for i in 0.. {
                let r = golden().join(format!("{case}.run{i}.jsonl"));
                if !r.exists() {
                    break;
                }
                runs.push(r);
            }
            out.insert(case.to_string(), runs);
        }
    }
    out
}

fn text(mut r: Report) -> String {
    r.labels = (0..r.labels.len()).map(|i| format!("run{i}")).collect();
    format!("{}\n", serde_json::to_string_pretty(&r).unwrap())
}

#[test]
fn every_golden_case_gives_the_pre_refactor_report_in_memory_and_from_files() {
    let cases = cases();
    assert!(cases.len() >= 60, "the corpus is there ({} cases)", cases.len());
    let tmp = tempfile::tempdir().unwrap();
    for (case, runs) in &cases {
        assert!(runs.len() >= 2, "{case}");
        let want = std::fs::read_to_string(golden().join(format!("{case}.report.json"))).unwrap();
        let labels: Vec<String> = (0..runs.len()).map(|i| format!("run{i}")).collect();
        // in memory (MemTrace)
        let traces: Vec<_> = runs.iter().map(|p| read_trace(p).unwrap()).collect();
        assert_eq!(text(verify(&traces, &labels)), want, "{case}: verify over in-memory traces");
        // from files written to a temporary directory (FileTrace)
        let copies: Vec<PathBuf> = runs
            .iter()
            .enumerate()
            .map(|(i, p)| {
                let c = tmp.path().join(format!("{case}-{i}.jsonl"));
                std::fs::copy(p, &c).unwrap();
                c
            })
            .collect();
        assert_eq!(text(verify_paths(&copies).unwrap()), want, "{case}: verify_paths");
        assert_eq!(text(verify_paths_ignoring(&copies, &[]).unwrap()), want, "{case}: verify_paths_ignoring");
    }
}
