/* Native LINE / PY_START recorder for sysmon_capture.py (Python 3.12+).
 *
 * The same "count" strategy as the pure-Python callbacks in sysmon_capture.SysmonCapture._make_callbacks, without a
 * Python frame per event: the first hit of a location in the current context appends one value (file id << 24 |
 * line) to a flat buffer; the next `hot` hits only count; past that the callback returns sys.monitoring.DISABLE and
 * remembers the code object, which Python re-arms at the next context switch.
 *
 * Built on demand by sysmon_capture.load_native() with the interpreter's own compiler settings; when it cannot be
 * built, the pure-Python callbacks are used (same output).
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>

#if PY_VERSION_HEX < 0x030D0000
#define Py_IsFinalizing _Py_IsFinalizing
#endif

typedef struct {
    void *code;     /* borrowed: Python keeps every armed code object alive */
    uint64_t fid;   /* file id << 24 */
    int64_t entry;  /* entry line for PY_START, -1 if none */
} CodeSlot;

typedef struct {
    uint64_t key;   /* recorded value */
    uint32_t gen;   /* context generation; a slot of an older generation is free */
    uint32_t cnt;   /* repeat hits in this generation */
} SeenSlot;

typedef struct {
    PyObject_HEAD
    CodeSlot *cm;
    size_t cm_cap, cm_n;
    SeenSlot *sn;
    size_t sn_cap, sn_n;  /* sn_n: slots of the current generation */
    uint32_t gen;
    uint64_t *buf;
    size_t n, cap;
    uint32_t hot;
    PyObject *disable;
    PyObject *hot_codes;  /* dict id(code) -> code, disabled locations in the current context */
} Rec;

static inline size_t mix(uint64_t x) {
    x ^= x >> 33;
    x *= 0xff51afd7ed558ccdULL;
    x ^= x >> 33;
    return (size_t)x;
}

static CodeSlot *cm_find(Rec *r, void *code) {
    size_t m = r->cm_cap - 1, i = mix((uint64_t)(uintptr_t)code) & m;
    for (;;) {
        CodeSlot *s = &r->cm[i];
        if (s->code == code) return s;
        if (s->code == NULL) return NULL;
        i = (i + 1) & m;
    }
}

static int cm_put(Rec *r, void *code, uint64_t fid, int64_t entry) {
    if ((r->cm_n + 1) * 2 > r->cm_cap) {
        size_t nc = r->cm_cap ? r->cm_cap * 2 : 1024;
        CodeSlot *old = r->cm, *nw = PyMem_Calloc(nc, sizeof(CodeSlot));
        if (!nw) { PyErr_NoMemory(); return -1; }
        size_t oc = r->cm_cap;
        r->cm = nw; r->cm_cap = nc; r->cm_n = 0;
        for (size_t j = 0; j < oc; j++)
            if (old[j].code) cm_put(r, old[j].code, old[j].fid, old[j].entry);
        PyMem_Free(old);
    }
    size_t m = r->cm_cap - 1, i = mix((uint64_t)(uintptr_t)code) & m;
    for (;;) {
        CodeSlot *s = &r->cm[i];
        if (s->code == code || s->code == NULL) {
            if (s->code == NULL) r->cm_n++;
            s->code = code; s->fid = fid; s->entry = entry;
            return 0;
        }
        i = (i + 1) & m;
    }
}

static int sn_grow(Rec *r) {
    size_t nc = r->sn_cap * 2, oc = r->sn_cap;
    SeenSlot *old = r->sn, *nw = PyMem_Calloc(nc, sizeof(SeenSlot));
    if (!nw) { PyErr_NoMemory(); return -1; }
    r->sn = nw; r->sn_cap = nc;
    size_t m = nc - 1;
    for (size_t j = 0; j < oc; j++) {
        if (old[j].gen != r->gen) continue;
        size_t i = mix(old[j].key) & m;
        while (nw[i].gen == r->gen) i = (i + 1) & m;
        nw[i] = old[j];
    }
    PyMem_Free(old);
    return 0;
}

static int buf_push(Rec *r, uint64_t v) {
    if (r->n == r->cap) {
        size_t nc = r->cap ? r->cap * 2 : 65536;
        uint64_t *nb = PyMem_Realloc(r->buf, nc * sizeof(uint64_t));
        if (!nb) { PyErr_NoMemory(); return -1; }
        r->buf = nb; r->cap = nc;
    }
    r->buf[r->n++] = v;
    return 0;
}

/* One event for value k: NULL on error, else a new reference to None or DISABLE. */
static PyObject *hit(Rec *r, uint64_t k, PyObject *code) {
    size_t m = r->sn_cap - 1, i = mix(k) & m;
    for (;;) {
        SeenSlot *s = &r->sn[i];
        if (s->gen != r->gen) {  /* free: first hit in this context */
            s->key = k; s->gen = r->gen; s->cnt = 0;
            r->sn_n++;
            if (buf_push(r, k) < 0) return NULL;
            if (r->sn_n * 2 > r->sn_cap && sn_grow(r) < 0) return NULL;
            Py_RETURN_NONE;
        }
        if (s->key == k) {
            if (s->cnt < r->hot) { s->cnt++; Py_RETURN_NONE; }
            PyObject *id = PyLong_FromVoidPtr(code);
            if (!id) return NULL;
            int e = PyDict_SetItem(r->hot_codes, id, code);
            Py_DECREF(id);
            if (e < 0) return NULL;
            Py_INCREF(r->disable);
            return r->disable;
        }
        i = (i + 1) & m;
    }
}

static PyObject *rec_line(Rec *r, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 2) { PyErr_SetString(PyExc_TypeError, "line(code, lineno)"); return NULL; }
    CodeSlot *c = cm_find(r, args[0]);
    if (!c) Py_RETURN_NONE;
    long ln = PyLong_AsLong(args[1]);
    if (ln == -1 && PyErr_Occurred()) return NULL;
    if (ln < 0) Py_RETURN_NONE;
    return hit(r, c->fid | (uint64_t)ln, args[0]);
}

static PyObject *rec_start(Rec *r, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 2) { PyErr_SetString(PyExc_TypeError, "start(code, offset)"); return NULL; }
    CodeSlot *c = cm_find(r, args[0]);
    if (!c || c->entry < 0) Py_RETURN_NONE;
    return hit(r, c->fid | (uint64_t)c->entry, args[0]);
}

static PyObject *rec_add_code(Rec *r, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 3) { PyErr_SetString(PyExc_TypeError, "add_code(code, fid, entry)"); return NULL; }
    unsigned long long fid = PyLong_AsUnsignedLongLong(args[1]);
    if (fid == (unsigned long long)-1 && PyErr_Occurred()) return NULL;
    long long entry = PyLong_AsLongLong(args[2]);
    if (entry == -1 && PyErr_Occurred()) return NULL;
    if (cm_put(r, args[0], (uint64_t)fid, (int64_t)entry) < 0) return NULL;
    Py_RETURN_NONE;
}

/* New context: forget the seen locations; return the code objects to re-arm (and reset that set). */
static PyObject *rec_switch(Rec *r, PyObject *unused) {
    r->gen++;
    if (r->gen == 0) {  /* wrapped: every slot would look current */
        memset(r->sn, 0, r->sn_cap * sizeof(SeenSlot));
        r->gen = 1;
    }
    r->sn_n = 0;
    PyObject *codes = PyDict_Values(r->hot_codes);
    if (!codes) return NULL;
    PyDict_Clear(r->hot_codes);
    return codes;
}

static PyObject *rec_tobytes(Rec *r, PyObject *unused) {
    return PyBytes_FromStringAndSize((const char *)r->buf, (Py_ssize_t)(r->n * sizeof(uint64_t)));
}

static Py_ssize_t rec_len(Rec *r) { return (Py_ssize_t)r->n; }

static int rec_init(Rec *r, PyObject *args, PyObject *kw) {
    PyObject *disable;
    unsigned int hot;
    if (!PyArg_ParseTuple(args, "OI", &disable, &hot)) return -1;
    Py_INCREF(disable);
    Py_XSETREF(r->disable, disable);
    r->hot = hot;
    if (!r->hot_codes && !(r->hot_codes = PyDict_New())) return -1;
    if (!r->sn) {
        r->sn_cap = 4096;
        if (!(r->sn = PyMem_Calloc(r->sn_cap, sizeof(SeenSlot)))) { PyErr_NoMemory(); return -1; }
        r->gen = 1;
    }
    if (!r->cm) {
        r->cm_cap = 1024;
        if (!(r->cm = PyMem_Calloc(r->cm_cap, sizeof(CodeSlot)))) { PyErr_NoMemory(); return -1; }
    }
    return 0;
}

static void rec_dealloc(Rec *r) {
    PyMem_Free(r->cm);
    PyMem_Free(r->sn);
    PyMem_Free(r->buf);
    Py_XDECREF(r->disable);
    Py_XDECREF(r->hot_codes);
    Py_TYPE(r)->tp_free((PyObject *)r);
}

static PyMethodDef rec_methods[] = {
    {"line", (PyCFunction)(void (*)(void))rec_line, METH_FASTCALL, "LINE callback"},
    {"start", (PyCFunction)(void (*)(void))rec_start, METH_FASTCALL, "PY_START callback"},
    {"add_code", (PyCFunction)(void (*)(void))rec_add_code, METH_FASTCALL, "add_code(code, fid << 24, entry or -1)"},
    {"switch", (PyCFunction)rec_switch, METH_NOARGS, "new context; returns the code objects to re-arm"},
    {"tobytes", (PyCFunction)rec_tobytes, METH_NOARGS, "recorded values as native uint64 bytes"},
    {NULL},
};

static PySequenceMethods rec_seq = {.sq_length = (lenfunc)rec_len};

static PyTypeObject RecType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_sysmon_rec.Recorder",
    .tp_basicsize = sizeof(Rec),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
    .tp_init = (initproc)rec_init,
    .tp_dealloc = (destructor)rec_dealloc,
    .tp_methods = rec_methods,
    .tp_as_sequence = &rec_seq,
};

/* Audit hook filtered in C: only the listed events reach the Python callable (a Python audit hook is called for
 * every event, e.g. the frequent "builtins.id" and "object.__getattr__"). Hooks cannot be removed; the callable and
 * the names stay referenced for the life of the process. */
typedef struct {
    PyObject *callable;
    Py_ssize_t n;
    const char **names;
} AuditFilter;

static int audit_hook(const char *event, PyObject *args, void *data) {
    AuditFilter *f = (AuditFilter *)data;
    if (Py_IsFinalizing()) return 0;
    for (Py_ssize_t i = 0; i < f->n; i++) {
        if (event[0] == f->names[i][0] && strcmp(event, f->names[i]) == 0) {
            PyObject *ev = PyUnicode_FromString(event);
            if (!ev) return -1;
            PyObject *a[2] = {ev, args};
            PyObject *r = PyObject_Vectorcall(f->callable, a, 2, NULL);
            Py_DECREF(ev);
            if (!r) return -1;
            Py_DECREF(r);
            return 0;
        }
    }
    return 0;
}

static PyObject *add_audit_hook(PyObject *self, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs != 2 || !PyCallable_Check(args[0]) || !PyTuple_Check(args[1])) {
        PyErr_SetString(PyExc_TypeError, "add_audit_hook(callable, tuple of event names)");
        return NULL;
    }
    Py_ssize_t n = PyTuple_GET_SIZE(args[1]);
    AuditFilter *f = PyMem_RawCalloc(1, sizeof(AuditFilter));
    const char **names = PyMem_RawCalloc(n ? n : 1, sizeof(char *));
    if (!f || !names) { PyMem_RawFree(f); PyMem_RawFree(names); return PyErr_NoMemory(); }
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *o = PyTuple_GET_ITEM(args[1], i);
        const char *c = PyUnicode_Check(o) ? PyUnicode_AsUTF8(o) : NULL;
        if (!c || !*c) {
            PyMem_RawFree(f); PyMem_RawFree(names);
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_TypeError, "event names must be non-empty str");
            return NULL;
        }
        size_t len = strlen(c) + 1;
        char *cp = PyMem_RawMalloc(len);
        if (!cp) { PyMem_RawFree(f); PyMem_RawFree(names); return PyErr_NoMemory(); }
        memcpy(cp, c, len);
        names[i] = cp;
    }
    Py_INCREF(args[0]);
    f->callable = args[0];
    f->n = n;
    f->names = names;
    if (PySys_AddAuditHook(audit_hook, f) < 0) return NULL;
    Py_RETURN_NONE;
}

static PyMethodDef mod_methods[] = {
    {"add_audit_hook", (PyCFunction)(void (*)(void))add_audit_hook, METH_FASTCALL,
     "add_audit_hook(callable, names): call callable(event, args) for the listed audit events only"},
    {NULL},
};

static struct PyModuleDef mod = {PyModuleDef_HEAD_INIT, .m_name = "_sysmon_rec", .m_size = -1,
                                 .m_methods = mod_methods};

PyMODINIT_FUNC PyInit__sysmon_rec(void) {
    if (PyType_Ready(&RecType) < 0) return NULL;
    PyObject *m = PyModule_Create(&mod);
    if (!m) return NULL;
    Py_INCREF(&RecType);
    if (PyModule_AddObject(m, "Recorder", (PyObject *)&RecType) < 0) { Py_DECREF(&RecType); Py_DECREF(m); return NULL; }
    return m;
}
