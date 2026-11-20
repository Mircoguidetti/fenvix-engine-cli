'use strict';
// The platform package (@fenvix/<triple>) for a process, or why the platform is not supported (src/native.js).

const SUPPORTED = ['linux-x64-gnu', 'linux-arm64-gnu', 'darwin-arm64'];
const GLIBC_MIN = [2, 28];

/** {triple, problem}: the platform package name for this process, or why there is none. */
function platformTriple(proc = process) {
  const { platform, arch } = proc;
  if (platform === 'darwin') {
    return arch === 'arm64' ? { triple: 'darwin-arm64' } : { triple: `darwin-${arch}`, problem: `macOS on ${arch} is not supported` };
  }
  if (platform === 'linux') {
    let glibc;
    try { glibc = proc.report.getReport().header.glibcVersionRuntime; } catch { glibc = undefined; }
    if (!glibc) return { triple: `linux-${arch}-musl`, problem: 'Linux without glibc (musl, e.g. Alpine) is not supported' };
    const v = String(glibc).split('.').map(Number);
    if (v[0] < GLIBC_MIN[0] || (v[0] === GLIBC_MIN[0] && (v[1] || 0) < GLIBC_MIN[1])) {
      return { triple: `linux-${arch}-gnu`, problem: `glibc ${glibc} is older than ${GLIBC_MIN.join('.')}` };
    }
    if (arch !== 'x64' && arch !== 'arm64') return { triple: `linux-${arch}-gnu`, problem: `Linux on ${arch} is not supported` };
    return { triple: `linux-${arch}-gnu` };
  }
  return { triple: `${platform}-${arch}`, problem: `${platform} is not supported` };
}

module.exports = { platformTriple, SUPPORTED, GLIBC_MIN };
