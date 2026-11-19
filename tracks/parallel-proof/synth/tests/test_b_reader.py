import pathlib, time
SHARED = pathlib.Path("/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd/synth/outside-shared.txt")

def test_b_reads():
    for _ in range(200):          # wait (real time) for the writer in another worker
        if SHARED.exists() and SHARED.read_text():
            break
        time.sleep(0.01)
    assert SHARED.read_text().strip() == "x"
