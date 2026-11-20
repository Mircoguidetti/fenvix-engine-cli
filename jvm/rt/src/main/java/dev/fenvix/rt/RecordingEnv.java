package dev.fenvix.rt;

import java.util.AbstractMap;
import java.util.Map;
import java.util.Set;

/** The map of System.getenv() that records which variables a test reads. */
final class RecordingEnv extends AbstractMap<String, String> {
    private final Map<String, String> inner;

    RecordingEnv(Map<String, String> inner) {
        this.inner = inner;
    }

    @Override
    public String get(Object k) {
        String v = inner.get(k);
        if (k instanceof String) Deps.env((String) k, v);
        return v;
    }

    @Override
    public boolean containsKey(Object k) {
        boolean b = inner.containsKey(k);
        if (k instanceof String) Deps.env((String) k, inner.get(k));
        return b;
    }

    @Override
    public Set<Entry<String, String>> entrySet() {
        Deps.env("*", null);
        return inner.entrySet();
    }

    @Override
    public int size() {
        return inner.size();
    }
}
