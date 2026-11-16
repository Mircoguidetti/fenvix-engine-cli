'use strict';
// Reversible patching of object properties.
class Patcher {
  constructor() {
    this.saved = [];
  }

  /** Replace obj[key] by value (keeps the original descriptor for undo). */
  set(obj, key, value) {
    const desc = Object.getOwnPropertyDescriptor(obj, key);
    this.saved.push([obj, key, desc]);
    if (desc && !desc.writable && !desc.set && desc.configurable) {
      Object.defineProperty(obj, key, { ...desc, value, writable: true });
    } else if (!desc || desc.writable || desc.set) {
      obj[key] = value;
      if (obj[key] !== value) Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: desc ? desc.enumerable : true });
    } else {
      Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: desc.enumerable });
    }
    return desc ? desc.value : undefined;
  }

  /** Define an own property (shadows a prototype method such as performance.now). */
  define(obj, key, value) {
    this.saved.push([obj, key, Object.getOwnPropertyDescriptor(obj, key)]);
    Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: false });
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
