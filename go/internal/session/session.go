// Package session is the configuration `fenvix-go test` hands to every
// `fenvix-go exec` it starts through `go test -exec` (one per package).
package session

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// Skip is the skip-with-proof configuration.
type Skip struct {
	Dir     string   `json:"dir"`     // cache directory (one file per package)
	Verify  bool     `json:"verify"`  // run every test anyway and compare reused outcomes
	Capture string   `json:"capture"` // "strace" (complete) or "hooks" (os-level hooks only: nothing is reused)
	Drop    []string `json:"drop"`    // fenvix's and go's own working state: never inputs
	Commit  string   `json:"commit"`  // informative
}

// Session is written once by `fenvix-go test`.
type Session struct {
	Dir         string            `json:"dir"`
	Self        string            `json:"self"`
	Det         bool              `json:"det"`
	Seed        uint64            `json:"seed"`
	Controls    []string          `json:"controls"`
	Ctl         uint32            `json:"ctl"`
	Unavailable map[string]string `json:"unavailable,omitempty"`
	Epoch       int64             `json:"epoch"`
	Shim        string            `json:"shim,omitempty"` // library preloaded into programs a --det test starts (their clock)
	Tick        int64             `json:"tick"`
	Adapt       int64             `json:"adapt"`
	MaxEvents   int               `json:"max_events"`
	Root        string            `json:"root"`
	Goroot      string            `json:"goroot"`
	GoVersion   string            `json:"go_version"`
	GOOS        string            `json:"goos"`
	GOARCH      string            `json:"goarch"`
	CgoEnabled  string            `json:"cgo_enabled"`
	GoMaxProcs  string            `json:"gomaxprocs,omitempty"`
	Pkgs        map[string]string `json:"pkgs"` // package dir -> import path
	Skip        *Skip             `json:"skip,omitempty"`
	OverlayHash string            `json:"overlay_digest"`
	BuildFlags  []string          `json:"build_flags"` // go test flags that change the binary (key)
}

// Path of the session file in dir.
func Path(dir string) string { return filepath.Join(dir, "session.json") }

// Save writes the session.
func (s *Session) Save() error {
	b, err := json.MarshalIndent(s, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(Path(s.Dir), b, 0o644)
}

// Load reads the session from dir.
func Load(dir string) (*Session, error) {
	b, err := os.ReadFile(Path(dir))
	if err != nil {
		return nil, fmt.Errorf("fenvix-go: no session in %s (exec is started by `fenvix-go test`): %w", dir, err)
	}
	var s Session
	if err := json.Unmarshal(b, &s); err != nil {
		return nil, err
	}
	return &s, nil
}
