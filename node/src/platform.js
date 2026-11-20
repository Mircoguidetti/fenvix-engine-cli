'use strict';
// The platform triple of a process and, when the engine has no native core for it, why (src/native.js).

const SUPPORTED = ['linux-x64-gnu'];
const GLIBC_MIN = [2, 28];

/** {triple, problem}: the platform triple of this process, and why it is not supported (absent when it is). */
function platformTriple(proc = process) {
  const { platform, arch } = proc;
  if (platform === 'darwin') return { triple: `darwin-${arch}`, problem: 'macOS is not supported' };
  if (platform === 'linux') {
    let glibc;
    try { glibc = proc.report.getReport().header.glibcVersionRuntime; } catch { glibc = undefined; }
    if (!glibc) return { triple: `linux-${arch}-musl`, problem: 'Linux without glibc (musl, e.g. Alpine) is not supported' };
    const v = String(glibc).split('.').map(Number);
    if (v[0] < GLIBC_MIN[0] || (v[0] === GLIBC_MIN[0] && (v[1] || 0) < GLIBC_MIN[1])) {
      return { triple: `linux-${arch}-gnu`, problem: `glibc ${glibc} is older than ${GLIBC_MIN.join('.')}` };
    }
    if (arch !== 'x64') return { triple: `linux-${arch}-gnu`, problem: `Linux on ${arch} is not supported` };
    return { triple: `linux-${arch}-gnu` };
  }
  return { triple: `${platform}-${arch}`, problem: `${platform} is not supported` };
}

module.exports = { platformTriple, SUPPORTED, GLIBC_MIN };
