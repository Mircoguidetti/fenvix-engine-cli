package embedpat

import (
	"embed"
	"testing"
)

//go:embed testdata/*.txt
var files embed.FS

func TestOneEmbedded(t *testing.T) {
	es, _ := files.ReadDir("testdata")
	if len(es) != 1 {
		t.Fatalf("%d embedded files", len(es))
	}
}

var extra bool

func TestNoExtraFile(t *testing.T) {
	if extra {
		t.Fatal("a file of the package changed the behaviour")
	}
}
