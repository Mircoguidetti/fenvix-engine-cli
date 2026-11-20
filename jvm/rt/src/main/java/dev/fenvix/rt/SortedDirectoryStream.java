package dev.fenvix.rt;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/** A directory stream read eagerly and, under --det, iterated in name order. */
final class SortedDirectoryStream implements DirectoryStream<Path> {
    private final DirectoryStream<Path> inner;
    private final List<Path> entries = new ArrayList<>();
    private boolean iterated;

    SortedDirectoryStream(DirectoryStream<Path> inner, boolean sort) throws IOException {
        this.inner = inner;
        try {
            for (Path p : inner) entries.add(p);
        } catch (java.nio.file.DirectoryIteratorException e) {
            throw e.getCause();
        }
        if (sort) entries.sort((a, b) -> a.toString().compareTo(b.toString()));
    }

    List<String> names() {
        List<String> n = new ArrayList<>(entries.size());
        for (Path p : entries) {
            Path f = p.getFileName();
            n.add(f == null ? p.toString() : f.toString());
        }
        return n;
    }

    @Override
    public Iterator<Path> iterator() {
        if (iterated) throw new IllegalStateException("Iterator already obtained");
        iterated = true;
        return entries.iterator();
    }

    @Override
    public void close() throws IOException {
        inner.close();
    }
}
