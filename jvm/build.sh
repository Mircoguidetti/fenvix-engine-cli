#!/usr/bin/env bash
# Build the JVM shell: Rust core (JNI) + runtime + agent (ASM shaded) + Maven extension.
# Output: jvm/dist/fenvix-agent.jar (one jar: agent, runtime, native library, init script, Maven extension, CLI).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
profile="${FENVIX_PROFILE:-release}"
(cd "$root" && cargo build -p fenvix-jvm --release -q)
(cd "$here" && mvn -q -B -DskipTests package)
stage="$here/target/stage"
rm -rf "$stage" && mkdir -p "$stage/fenvix" "$here/dist"
cp "$here/rt/target/fenvix-rt-0.1.0.jar" "$stage/fenvix/fenvix-rt.jar"
cp "$root/target/release/libfenvix_jvm.so" "$stage/fenvix/libfenvix_jvm.so"
cp "$here/gradle/fenvix.init.gradle" "$stage/fenvix/fenvix.init.gradle"
cp "$here/maven-ext/target/fenvix-maven-ext.jar" "$stage/fenvix/fenvix-maven-ext.jar"
cp "$here/agent/target/fenvix-agent.jar" "$here/dist/fenvix-agent.jar"
(cd "$stage" && jar uf "$here/dist/fenvix-agent.jar" fenvix)
echo "built $here/dist/fenvix-agent.jar"
