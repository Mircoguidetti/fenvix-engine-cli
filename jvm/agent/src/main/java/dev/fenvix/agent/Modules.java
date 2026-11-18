package dev.fenvix.agent;

import dev.fenvix.rt.Det;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * Java 9+: java.base reads the runtime's (bootstrap, unnamed) module, and
 * java.lang, java.util and java.util.concurrent are opened to it (reseeding
 * the JDK's hidden generators). Reflection, so that the agent loads on Java 8.
 */
final class Modules {
    private Modules() {}

    static void open(Instrumentation inst) throws Exception {
        Method getModule = Class.class.getMethod("getModule");
        Object rt = getModule.invoke(Det.class);
        Object base = getModule.invoke(Object.class);
        Set<Object> rts = Collections.singleton(rt);
        Map<String, Set<Object>> opens = new HashMap<>();
        for (String p : new String[] {"java.lang", "java.util", "java.util.concurrent"}) opens.put(p, rts);
        Class<?> moduleClass = Class.forName("java.lang.Module");
        Method m = Instrumentation.class.getMethod("redefineModule", moduleClass, Set.class, Map.class, Map.class, Set.class, Map.class);
        m.invoke(inst, base, new HashSet<>(rts), new HashMap<>(), opens, new HashSet<>(), new HashMap<>());
    }
}
