export const slug = (text) => text.toLowerCase().split(/\s+/).filter(Boolean).join('-');
