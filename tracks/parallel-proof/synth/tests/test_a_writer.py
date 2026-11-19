import pathlib
SHARED = pathlib.Path("/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd/synth/outside-shared.txt")

def test_a_writes():
    SHARED.write_text(open(pathlib.Path(__file__).parent / "value.txt").read())
