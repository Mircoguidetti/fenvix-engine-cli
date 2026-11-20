# The closed network, recording and replay

Under `--det` a test cannot reach the network, because a response that changes from run to run would make the
run non-deterministic. External services are recorded once and replayed in every later run.

## What is blocked

| reached by the test | under `--det` |
|---|---|
| loopback (`127.0.0.0/8`, `::1`, `localhost`, `*.localhost`), Unix sockets | allowed |
| a host given with `--det-allow-host=HOST` (repeatable) | allowed (live: its answers are not controlled) |
| any other host: TCP `connect`, UDP `sendto`, DNS (`getaddrinfo`, `gethostbyname[_ex]`) | blocked: `detpy.NetworkBlockedError` (a `ConnectionRefusedError`), or `socket.gaierror` for DNS |
| reverse lookups (`gethostbyaddr`, `getnameinfo`) of external addresses | blocked: `socket.herror` naming the address |
| `getfqdn(name)` of an external name | the name itself, without a lookup |
| a local HTTP(S) proxy from `*_PROXY` | counts as external: blocked, recorded and replayed like the host behind it |
| child processes (`subprocess`, `os.system`) | their `http_proxy`, `https_proxy`, `ALL_PROXY` point at `127.0.0.1:9`, where nothing listens, with `NO_PROXY` set for local and allowed hosts. curl, wget, git, pip and urllib honour these variables. A child that ignores them is not controlled (the verifier reports `[child]`) |
| native clients that open their own sockets in C (grpcio, pycurl, libpq, ...) | not controlled (needs the syscall backend) |

The error a test sees names the host and how to proceed: `detpy: network access to example.com:443 blocked (Level 0
closes the network; localhost is allowed); use --det-record to record real responses, or --det-allow-host to allow
it` (in replay: `no recording for it in this test: re-run with --det-record`).

## Recording and replay

```bash
fenvix pytest --det-record            # the network is open; every external connection is recorded per test
fenvix pytest                         # later runs replay from .detpy/cassette.json (or --det-cassette=PATH)
```

* **What is stored.** The byte stream of each connection, above TLS (plaintext), per test, in order: host, port,
  whether it used TLS, and the sent and received segments (base64) in `.detpy/cassette.json`, plus the date each
  test was recorded. The cassette is meant to be committed: `.detpy/.gitignore` ignores everything else in
  `.detpy/`.
* **Secrets.** The values of `Authorization`, `Proxy-Authorization`, `Cookie`, `X-Api-Key`, `Api-Key`, `X-Auth-Token`,
  `X-Access-Token`, `X-Amz-Security-Token`, `X-Goog-Api-Key`, `X-Csrf-Token` and `Private-Token` are replaced by `*`
  of the same length before the file is written. Replay compares requests with the same masking, so a rotated
  token of the same length still matches.
* **Matching.** The n-th connection of a test to `host:port` replays the n-th recorded one. Replay reads what the
  test sends and compares it with the recording. If the request differs (another path, another body), the recorded
  answer is not served: the test reads end of file, the trace gets a `replay.mismatch` event, and the run ends with
  `network: replay refused for N test(s): the request differs from the recorded one`. Re-record with `--det-record`.
* **TCP.** Blocking sockets (`requests`, `urllib`, `urllib3`, `httpx`), `sendmsg`/`recvmsg`, TLS
  through `ssl` (`SSLContext.wrap_socket`: on replay the socket is an `ssl.SSLSocket` over the recorded plaintext that
  answers the recorded version, cipher, ALPN protocol and peer certificate, in both forms), and asyncio clients (`aiohttp`, `httpx.AsyncClient`, `asyncio.open_connection`).
* **UDP.** Datagrams sent with `sendto` to an external host are recorded one by one, with the answers received
  from that host (`recvfrom`, `recvfrom_into`). On replay, a sent datagram that equals the recorded one is answered
  by the recorded datagrams from a local socket. The answers come back as real datagrams, so `select` and asyncio
  see them, and their source address is the recorded host's. Another datagram is not answered (refused, as for
  TCP). DNS over UDP (dnspython), statsd and syslog clients are covered this way.
* **What is not covered.** Native clients are not covered (see above).
* **Staleness.** `--det-cassette-max-age=DAYS` refuses to replay recordings older than DAYS, or recordings
  without a date. Those tests meet the closed network until they are recorded again. The cassette's digest is a run
  input, so `fenvix verify` reports runs with different cassettes as divergent (`[net]`).
* **Re-recording.** `--det-record` replaces the recordings of the tests that ran and keeps the others.

## `fenvix cassette`

```bash
fenvix cassette list                              # test, connections, recording date, hosts
fenvix cassette rename OLD_ID NEW_ID              # a renamed or moved test keeps its recording
fenvix cassette drop TEST_ID...                   # remove recordings (the tests are blocked until re-recorded)
fenvix cassette --cassette path/to/c.json list    # another cassette
```

## Go, JVM

Go and JVM are out of the go-live scope. Their shells close the network but do not record or replay it.
