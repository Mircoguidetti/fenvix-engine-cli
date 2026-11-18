// Package core calls the Rust core (crates/fenvix-go, a C ABI over
// detpy-core) through cgo: the same events, BLAKE3 fingerprints, JSONL traces,
// verifier, seeds and shuffle as the Python and Node shells.
//
// Build the static library first: cargo build -p fenvix-go --release.
package core

/*
#cgo CFLAGS: -I${SRCDIR}/../../../crates/fenvix-go/include
#cgo LDFLAGS: ${SRCDIR}/../../../target/release/libfenvix_go.a -ldl -lm -lpthread
#include <stdlib.h>
#include "fenvix_go.h"
*/
import "C"

import (
	"encoding/json"
	"errors"
	"unsafe"
)

func lastError(what string) error {
	p := C.fenvix_last_error()
	if p == nil {
		return errors.New(what + ": unknown error")
	}
	return errors.New(what + ": " + C.GoString(p))
}

func take(p *C.char) string {
	if p == nil {
		return ""
	}
	s := C.GoString(p)
	C.fenvix_string_free(p)
	return s
}

func cstr(s string) *C.char { return C.CString(s) }

// EncodingVersion is the event encoding version of the core.
func EncodingVersion() uint32 { return uint32(C.fenvix_encoding_version()) }

// TraceVersion is the trace format version of the core.
func TraceVersion() uint32 { return uint32(C.fenvix_trace_version()) }

// Recorder fingerprints tests and streams a trace file.
type Recorder struct{ p *C.FenvixRecorder }

// NewRecorder creates a recorder (0 = core defaults).
func NewRecorder(maxEvents, checkpointEvery uint32) *Recorder {
	return &Recorder{p: C.fenvix_recorder_new(C.uint32_t(maxEvents), C.uint32_t(checkpointEvery))}
}

// Free releases the recorder.
func (r *Recorder) Free() {
	if r.p != nil {
		C.fenvix_recorder_free(r.p)
		r.p = nil
	}
}

// Open starts the trace at path.
func (r *Recorder) Open(path string, meta any, order []string) error {
	m, err := json.Marshal(meta)
	if err != nil {
		return err
	}
	if order == nil {
		order = []string{}
	}
	o, _ := json.Marshal(order)
	cp, cm, co := cstr(path), cstr(string(m)), cstr(string(o))
	defer C.free(unsafe.Pointer(cp))
	defer C.free(unsafe.Pointer(cm))
	defer C.free(unsafe.Pointer(co))
	if C.fenvix_recorder_open(r.p, cp, cm, co) != 0 {
		return lastError("open trace")
	}
	return nil
}

// BeginTest starts a test.
func (r *Recorder) BeginTest(nodeid string, index uint64) error {
	c := cstr(nodeid)
	defer C.free(unsafe.Pointer(c))
	if C.fenvix_recorder_begin_test(r.p, c, C.uint64_t(index)) != 0 {
		return lastError("begin test")
	}
	return nil
}

// Record records one event.
func (r *Recorder) Record(thread uint32, source, op, site, value string) error {
	cs, co, ca, cv := cstr(source), cstr(op), cstr(site), cstr(value)
	defer C.free(unsafe.Pointer(cs))
	defer C.free(unsafe.Pointer(co))
	defer C.free(unsafe.Pointer(ca))
	defer C.free(unsafe.Pointer(cv))
	if C.fenvix_recorder_record(r.p, C.uint32_t(thread), cs, co, ca, cv) != 0 {
		return lastError("record")
	}
	return nil
}

// RecordPacked records packed events (0x1E between events, 0x1F between fields).
func (r *Recorder) RecordPacked(data []byte) (int, error) {
	if len(data) == 0 {
		return 0, nil
	}
	n := C.fenvix_recorder_record_packed(r.p, (*C.uint8_t)(unsafe.Pointer(&data[0])), C.size_t(len(data)))
	if n < 0 {
		return 0, lastError("record packed")
	}
	return int(n), nil
}

// EndTest finishes the current test and returns its fingerprint.
func (r *Recorder) EndTest(outcome string) (string, error) {
	c := cstr(outcome)
	defer C.free(unsafe.Pointer(c))
	p := C.fenvix_recorder_end_test(r.p, c)
	if p == nil {
		if C.fenvix_last_error() != nil {
			return "", lastError("end test")
		}
		return "", nil
	}
	return take(p), nil
}

// Close writes the footer; returns the order digest.
func (r *Recorder) Close() (string, error) {
	p := C.fenvix_recorder_close(r.p)
	if p == nil && C.fenvix_last_error() != nil {
		return "", lastError("close trace")
	}
	return take(p), nil
}

// Dropped is the number of events received outside any test.
func (r *Recorder) Dropped() uint64 { return uint64(C.fenvix_recorder_dropped(r.p)) }

// VerifyText verifies traces and renders the report.
func VerifyText(paths []string, showStable bool) (string, error) {
	j, _ := json.Marshal(paths)
	c := cstr(string(j))
	defer C.free(unsafe.Pointer(c))
	s := C.int(0)
	if showStable {
		s = 1
	}
	p := C.fenvix_verify_text(c, s)
	if p == nil {
		return "", lastError("verify")
	}
	return take(p), nil
}

// VerifyJSON verifies traces and returns the report as JSON.
func VerifyJSON(paths []string) (string, error) {
	j, _ := json.Marshal(paths)
	c := cstr(string(j))
	defer C.free(unsafe.Pointer(c))
	p := C.fenvix_verify_json(c)
	if p == nil {
		return "", lastError("verify")
	}
	return take(p), nil
}

// DeriveSeed is the core's seed derivation (the same as Python and Node).
func DeriveSeed(base uint64, key string) uint64 {
	c := cstr(key)
	defer C.free(unsafe.Pointer(c))
	return uint64(C.fenvix_derive_seed(C.uint64_t(base), c))
}

// ShuffleIndices is the core's permutation of 0..n for group key.
func ShuffleIndices(n int, seed uint64, key string) []int {
	out := make([]C.uint32_t, n+1)
	c := cstr(key)
	defer C.free(unsafe.Pointer(c))
	if C.fenvix_shuffle_indices(C.uint32_t(n), C.uint64_t(seed), c, &out[0]) != 0 {
		panic(lastError("shuffle"))
	}
	res := make([]int, n)
	for i := 0; i < n; i++ {
		res[i] = int(out[i])
	}
	return res
}

// Digest is the core's short BLAKE3 digest of data.
func Digest(data []byte) string {
	var p *C.uint8_t
	if len(data) > 0 {
		p = (*C.uint8_t)(unsafe.Pointer(&data[0]))
	}
	return take(C.fenvix_digest(p, C.size_t(len(data))))
}

// DigestFile is the core's full BLAKE3 digest of a file ("" if unreadable).
func DigestFile(path string) string {
	c := cstr(path)
	defer C.free(unsafe.Pointer(c))
	return take(C.fenvix_digest_file(c))
}

// MergeResult is the result of MergeTraces.
type MergeResult struct {
	NTests      int      `json:"n_tests"`
	OrderDigest string   `json:"order_digest"`
	Skipped     []string `json:"skipped"`
}

// MergeTraces concatenates partial traces into one.
func MergeTraces(parts []string, out string, meta any, order []string) (*MergeResult, error) {
	if parts == nil {
		parts = []string{}
	}
	if order == nil {
		order = []string{}
	}
	pj, _ := json.Marshal(parts)
	mj, err := json.Marshal(meta)
	if err != nil {
		return nil, err
	}
	oj, _ := json.Marshal(order)
	cp, co, cm, cord := cstr(string(pj)), cstr(out), cstr(string(mj)), cstr(string(oj))
	defer C.free(unsafe.Pointer(cp))
	defer C.free(unsafe.Pointer(co))
	defer C.free(unsafe.Pointer(cm))
	defer C.free(unsafe.Pointer(cord))
	p := C.fenvix_merge_traces(cp, co, cm, cord)
	if p == nil {
		return nil, lastError("merge traces")
	}
	var r MergeResult
	if err := json.Unmarshal([]byte(take(p)), &r); err != nil {
		return nil, err
	}
	return &r, nil
}
