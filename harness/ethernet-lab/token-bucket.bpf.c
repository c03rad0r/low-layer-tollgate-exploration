// Per-source-MAC token bucket for EtherType 0x2121, as a tc/BPF classifier.
//
// One LRU hash keyed by source MAC holds the token count and the last refill
// time. Frames of other EtherTypes pass untouched. This is the tc/eBPF half of
// Exp E4 (the nft half is a dynamic set with `limit rate over`).
//
// Constants are fixed at build time: 1000 pps, burst 100 frames. The lab
// rebuilds with -DRATE_PPS/-DBURST to change them.
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/pkt_cls.h>

typedef __u64 u64;
typedef __u32 u32;
typedef __u16 u16;
typedef __u8 u8;

#define SEC(name) __attribute__((section(name), used))
#define __uint(name, val) int (*name)[val]
#define __type(name, val) typeof(val) *name

#ifndef RATE_PPS
#define RATE_PPS 1000
#endif
#ifndef BURST
#define BURST 100
#endif

static void *(*bpf_map_lookup_elem)(void *map, const void *key) = (void *)1;
static long (*bpf_map_update_elem)(void *map, const void *key,
                                   const void *value, u64 flags) = (void *)2;
static u64 (*bpf_ktime_get_ns)(void) = (void *)5;

struct mac_key {
    u8 addr[6];
    u16 pad;
};

struct bucket {
    u64 tokens;
    u64 last_ns;
    u64 rem;  // sub-token remainder, in units of 1/RATE_PPS ns
};

// Legacy `maps` section. The BTF-defined map form did not relocate under the
// iproute2/libbpf pair in the lab image (map fd arrived as 0 and the verifier
// rejected the lookup as `scalar expected=map_ptr`), so this object uses the
// older definition, which does.
struct bpf_map_def {
    unsigned int type;
    unsigned int key_size;
    unsigned int value_size;
    unsigned int max_entries;
    unsigned int map_flags;
};

struct bpf_map_def SEC("maps") buckets = {
    .type = BPF_MAP_TYPE_LRU_HASH,
    .key_size = sizeof(struct mac_key),
    .value_size = sizeof(struct bucket),
    .max_entries = 65536,
};

SEC("classifier")
int bucket_filter(struct __sk_buff *skb) {
    void *data = (void *)(long)skb->data;
    void *data_end = (void *)(long)skb->data_end;
    struct ethhdr *eth = data;

    if ((void *)(eth + 1) > data_end)
        return TC_ACT_OK;
    if (eth->h_proto != __builtin_bswap16(0x2121))
        return TC_ACT_OK;

    struct mac_key key = {};
    __builtin_memcpy(key.addr, eth->h_source, 6);

    u64 now = bpf_ktime_get_ns();
    struct bucket *b = bpf_map_lookup_elem(&buckets, &key);
    if (!b) {
        struct bucket init = {.tokens = BURST - 1, .last_ns = now, .rem = 0};
        bpf_map_update_elem(&buckets, &key, &init, BPF_ANY);
        return TC_ACT_OK;
    }

    // Exact refill: carry the sub-token remainder so a 1 ms cadence does not
    // lose half the frames to integer truncation. Cap the elapsed time at one
    // second; max intermediate is 1e9 * RATE_PPS = 1e12, well inside u64.
    u64 elapsed = now - b->last_ns;
    if (elapsed > 1000000000ULL)
        elapsed = 1000000000ULL;
    u64 num = elapsed * (u64)RATE_PPS + b->rem;
    u64 add = num / 1000000000ULL;
    b->rem = num % 1000000000ULL;
    u64 tokens = b->tokens + add;
    if (tokens > BURST)
        tokens = BURST;
    b->last_ns = now;
    if (tokens > 0) {
        b->tokens = tokens - 1;
        return TC_ACT_OK;
    }
    b->tokens = 0;
    return TC_ACT_SHOT;
}

char _license[] SEC("license") = "GPL";
