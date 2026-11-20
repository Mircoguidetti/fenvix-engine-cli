package dev.fenvix.junit;

/** Shared flags (no JUnit references: loadable whatever JUnit versions are present). */
final class Flags {
    private Flags() {}

    /** A JUnit Platform plan is running: the JUnit 4 hook stays silent (Vintage). */
    static volatile boolean platformActive;
}
