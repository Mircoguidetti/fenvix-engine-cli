package org.codehaus.plexus.rvutil;

/** Project code in a package the agent treats as test infrastructure (org/codehaus/plexus/): plexus-utils, Maven plugins. */
public final class Words {
    private Words() {}

    public static String join(String a, String b) {
        return a + "-" + b;
    }
}
