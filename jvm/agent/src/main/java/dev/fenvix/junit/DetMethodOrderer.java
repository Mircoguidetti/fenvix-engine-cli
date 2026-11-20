package dev.fenvix.junit;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.MethodDescriptor;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.MethodOrdererContext;

/**
 * Method order under --det (junit.jupiter.testmethod.order.default). Seed 0:
 * the list is left as Jupiter's own default order (fixed: method-name hash),
 * which also overrides a project-wide random default orderer. Seed N: methods
 * sorted by name and parameter types, then shuffled reproducibly with the Rust
 * core (group key = class name).
 */
public class DetMethodOrderer implements MethodOrderer {
    static String key(Method m) {
        StringBuilder sb = new StringBuilder(m.getName()).append('(');
        Class<?>[] p = m.getParameterTypes();
        for (int i = 0; i < p.length; i++) {
            if (i > 0) sb.append(", ");
            sb.append(p[i].getName());
        }
        return sb.append(')').toString();
    }

    @Override
    public void orderMethods(MethodOrdererContext ctx) {
        if (Order.seed() == 0) return;
        List<? extends MethodDescriptor> l = ctx.getMethodDescriptors();
        List<String> names = new ArrayList<>();
        for (MethodDescriptor d : l) names.add(key(d.getMethod()));
        names.sort(Comparator.naturalOrder());
        Map<String, Integer> rank = Order.rank(names, Order.seed(), ctx.getTestClass().getName());
        l.sort(Comparator.comparingInt((MethodDescriptor d) -> rank.getOrDefault(key(d.getMethod()), Integer.MAX_VALUE)));
    }
}
