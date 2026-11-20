package dep

import "os"

// Config is loaded by init (a dependency package).
var Config string

func init() {
	b, _ := os.ReadFile(os.Getenv("R025_CFG"))
	Config = string(b)
}
