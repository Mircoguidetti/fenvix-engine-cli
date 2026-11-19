/* C ABI of detpy-core for the fenvix-go shell (cgo). See crates/fenvix-go/src/lib.rs.
 *
 * Strings in: NUL-terminated UTF-8. Strings out: free with fenvix_string_free.
 * Errors: negative status or NULL; message in fenvix_last_error() (per thread,
 * owned by the library). Packed events: events separated by 0x1E, fields by
 * 0x1F: source, op, site, value, optional thread. */
#ifndef FENVIX_GO_H
#define FENVIX_GO_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct FenvixRecorder FenvixRecorder;

uint32_t fenvix_encoding_version(void);
uint32_t fenvix_trace_version(void);
const char *fenvix_last_error(void);
void fenvix_string_free(char *s);

FenvixRecorder *fenvix_recorder_new(uint32_t max_events, uint32_t checkpoint_every);
void fenvix_recorder_free(FenvixRecorder *r);
int fenvix_recorder_open(FenvixRecorder *r, const char *path, const char *meta_json, const char *order_json);
int fenvix_recorder_begin_test(FenvixRecorder *r, const char *nodeid, uint64_t index);
int fenvix_recorder_record(FenvixRecorder *r, uint32_t thread, const char *source, const char *op,
                           const char *site, const char *value);
int64_t fenvix_recorder_record_packed(FenvixRecorder *r, const uint8_t *data, size_t len);
char *fenvix_recorder_end_test(FenvixRecorder *r, const char *outcome);
char *fenvix_recorder_close(FenvixRecorder *r);
uint64_t fenvix_recorder_dropped(FenvixRecorder *r);
char *fenvix_recorder_finished_json(FenvixRecorder *r);

char *fenvix_verify_json(const char *paths_json);
char *fenvix_verify_text(const char *paths_json, int show_stable);

uint64_t fenvix_derive_seed(uint64_t base, const char *key);
int fenvix_shuffle_indices(uint32_t n, uint64_t seed, const char *key, uint32_t *out);
char *fenvix_order_digest(const char *ids_json);
char *fenvix_digest(const uint8_t *data, size_t len);
char *fenvix_digest_file(const char *path);
char *fenvix_merge_traces(const char *parts_json, const char *out, const char *meta_json, const char *order_json);
char *fenvix_backends(void);

typedef struct FenvixSkip FenvixSkip;
char *fenvix_skip_strace_args(const char *log);
FenvixSkip *fenvix_skip_open(const char *config_json);
char *fenvix_skip_decide(FenvixSkip *h, const char *names_json);
char *fenvix_skip_record(FenvixSkip *h, const char *run_json);
void fenvix_skip_free(FenvixSkip *h);
char *fenvix_virtual_proc_stat(const char *real);
int64_t fenvix_skip_day_epoch(void);
char *fenvix_skip_summary(const char *decisions, const char *report, int real_clock);

#ifdef __cplusplus
}
#endif
#endif
