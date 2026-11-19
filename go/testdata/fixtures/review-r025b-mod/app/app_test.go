package app

import (
	"testing"

	"example.com/dep"
)

func TestDepValue(t *testing.T) {
	if dep.Value() != "A" {
		t.Fatal(dep.Value())
	}
}
