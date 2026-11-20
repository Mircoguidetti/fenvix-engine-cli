// The virtual pid (--det without a PID namespace) still names this process
// wherever package os and package syscall take a pid.
package vpid

import (
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestMain(m *testing.M) {
	if os.Getenv("VPID_CHILD") == "1" {
		os.Stdout.WriteString(strconv.Itoa(os.Getpid()))
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func TestPidStable(t *testing.T) {
	t.Logf("pid=%d", os.Getpid())
}

func TestSignalSelf(t *testing.T) {
	c := make(chan os.Signal, 1)
	signal.Notify(c, syscall.SIGUSR1)
	defer signal.Stop(c)
	wait := func(what string) {
		select {
		case <-c:
		case <-time.After(5 * time.Second):
			t.Fatalf("%s: signal not delivered", what)
		}
	}
	if err := syscall.Kill(os.Getpid(), syscall.SIGUSR1); err != nil {
		t.Fatal("syscall.Kill:", err)
	}
	wait("syscall.Kill")
	p, err := os.FindProcess(os.Getpid())
	if err != nil {
		t.Fatal(err)
	}
	if err := p.Signal(syscall.SIGUSR1); err != nil {
		t.Fatal("Process.Signal:", err)
	}
	wait("Process.Signal")
}

func TestProcPidIsSelf(t *testing.T) {
	b, err := os.ReadFile("/proc/" + strconv.Itoa(os.Getpid()) + "/status")
	if err != nil {
		t.Fatal(err)
	}
	self, _ := os.ReadFile("/proc/self/status")
	name := func(s []byte) string { return strings.SplitN(string(s), "\n", 2)[0] }
	if name(b) != name(self) {
		t.Fatalf("/proc/<pid>/status is %q, /proc/self/status %q", name(b), name(self))
	}
}

func TestChildHasItsOwnPid(t *testing.T) {
	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), "VPID_CHILD=1")
	out, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != strconv.Itoa(cmd.Process.Pid) {
		t.Fatalf("child reports pid %s; its real pid is %d, the parent's %d", out, cmd.Process.Pid, os.Getpid())
	}
}
