'use strict';
// Reversible patching of object properties. Never throws: a property that
// cannot be replaced (non-configurable, read-only) is reported and left alone.
class Patcher {
  constructor() {
    this.saved = [];
    this.failed = [];
  }

  /** Replace obj[key] by value; returns true when the property now holds value. */
  set(obj, key, value) {
    const desc = Object.getOwnPropertyDescriptor(obj, key);
    try {
      if (!desc) {
        obj[key] = value;
        if (obj[key] !== value) {
          Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: true });
        }
      } else if ('value' in desc) {
        if (desc.writable) obj[key] = value;
        else if (desc.configurable) Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: desc.enumerable });
      } else if (desc.set) {
        obj[key] = value;
        if (obj[key] !== value && desc.configurable) {
          Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: desc.enumerable });
        }
      } else if (desc.configurable) {
        Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: desc.enumerable });
      }
    } catch { /* reported below */ }
    if (obj[key] !== value) {
      this.failed.push(String(key));
      return false;
    }
    this.saved.push([obj, key, desc]);
    return true;
  }

  /** Define an own property (shadows a prototype method such as performance.now). */
  define(obj, key, value) {
    const desc = Object.getOwnPropertyDescriptor(obj, key);
    try {
      Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: false });
    } catch {
      this.failed.push(String(key));
      return false;
    }
    this.saved.push([obj, key, desc]);
    return true;
  }

  undoAll() {
    for (let i = this.saved.length - 1; i >= 0; i--) {
      const [obj, key, desc] = this.saved[i];
      try {
        if (desc) Object.defineProperty(obj, key, desc);
        else delete obj[key];
      } catch { /* frozen: leave it */ }
    }
    this.saved = [];
  }
}
module.exports = { Patcher };
