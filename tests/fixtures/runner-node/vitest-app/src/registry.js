// A module-level registry: state shared by every test of a file (the cause of the order-dependent failure).
export const registry = [];
export const register = (name) => { registry.push(name); return registry.length; };
export const add = (a, b) => a + b;
