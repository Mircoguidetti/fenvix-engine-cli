package dev.fenvix.junit;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.ClassDescriptor;
import org.junit.jupiter.api.ClassOrderer;
import org.junit.jupiter.api.ClassOrdererContext;

/**
 * Class order under --det (junit.jupiter.testclass.order.default): seed 0 =
 * fixed order (by class name); seed N = the reproducible SplitMix64 shuffle of
 * the Rust core ({@code shuffle_indices}, as in Python and Node), group key
 * {@code classes:<module>}.
 */
public class DetClassOrderer implements ClassOrderer {
    @Override
    public void orderClasses(ClassOrdererContext ctx) {
        List<? extends ClassDescriptor> l = ctx.getClassDescriptors();
        List<String> names = new ArrayList<>();
        for (ClassDescriptor d : l) names.add(d.getTestClass().getName());
        names.sort(Comparator.naturalOrder());
        long seed = Order.seed();
        Map<String, Integer> rank = Order.rank(names, seed, "classes:" + Ids.module(System.getProperty("fenvix.module", "")));
        l.sort(Comparator.comparingInt((ClassDescriptor d) -> rank.getOrDefault(d.getTestClass().getName(), Integer.MAX_VALUE)));
    }
}
