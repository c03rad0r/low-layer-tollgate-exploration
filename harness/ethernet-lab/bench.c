// Minimal AF_PACKET sender/receiver for the frame-gate labs.
//
//   bench send <ifname> <pps> <seconds> <size> [src_mac]
//   bench recv <ifname> <seconds>
//   bench recvmac <ifname> <seconds>
//
// Frames carry EtherType 0x2121 so they hit the same nft/tc rules as FIPS.
// `recvmac` counts survivors per source MAC, which is how the per-MAC token
// bucket is observed behind a bridge.
#include <arpa/inet.h>
#include <errno.h>
#include <linux/if_ether.h>
#include <linux/if_packet.h>
#include <net/if.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static long long now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void sleep_ns(long long ns) {
    if (ns <= 0) return;
    struct timespec ts = { .tv_sec = ns / 1000000000LL,
                           .tv_nsec = ns % 1000000000LL };
    nanosleep(&ts, NULL);
}

static int parse_mac(const char *text, unsigned char *out) {
    unsigned int b[6];
    if (sscanf(text, "%x:%x:%x:%x:%x:%x",
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5]) != 6)
        return -1;
    for (int i = 0; i < 6; i++) out[i] = (unsigned char)b[i];
    return 0;
}

static int open_socket(const char *ifname, unsigned *ifindex_out) {
    unsigned ifindex = if_nametoindex(ifname);
    if (!ifindex) { perror("if_nametoindex"); return -1; }
    int fd = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_ALL));
    if (fd < 0) { perror("socket"); return -1; }
    int buf = 8 * 1024 * 1024;
    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &buf, sizeof buf);
    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &buf, sizeof buf);
    struct sockaddr_ll sll;
    memset(&sll, 0, sizeof sll);
    sll.sll_family = AF_PACKET;
    sll.sll_protocol = htons(ETH_P_ALL);
    sll.sll_ifindex = (int)ifindex;
    if (bind(fd, (struct sockaddr *)&sll, sizeof sll) < 0) {
        perror("bind"); close(fd); return -1;
    }
    *ifindex_out = ifindex;
    return fd;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: bench send|recv|recvmac <if> ...\n");
        return 2;
    }
    const char *mode = argv[1];
    const char *ifname = argv[2];
    unsigned ifindex = 0;
    int fd = open_socket(ifname, &ifindex);
    if (fd < 0) return 1;

    if (strcmp(mode, "send") == 0) {
        if (argc < 5) { fprintf(stderr, "send needs pps and seconds\n"); return 2; }
        long pps = atol(argv[3]);
        double secs = atof(argv[4]);
        int size = argc > 5 ? atoi(argv[5]) : 64;
        if (size < 14 || size > 1500) size = 64;

        unsigned char src[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x01};
        if (argc > 6 && parse_mac(argv[6], src) != 0) {
            fprintf(stderr, "bad src mac %s\n", argv[6]);
            return 2;
        }

        unsigned char frame[1600];
        memset(frame, 0xab, sizeof frame);
        memset(frame, 0xff, 6);            // broadcast
        memcpy(frame + 6, src, 6);         // source
        frame[12] = 0x21; frame[13] = 0x21; // 0x2121

        struct sockaddr_ll dst;
        memset(&dst, 0, sizeof dst);
        dst.sll_family = AF_PACKET;
        dst.sll_protocol = htons(ETH_P_ALL);
        dst.sll_ifindex = (int)ifindex;
        dst.sll_halen = 6;
        memcpy(dst.sll_addr, frame, 6);    // broadcast

        // Pace in bursts. For rates above 1 kpps, send pps/1000 frames per
        // 1 ms tick; below 1 kpps, send one frame every 1e9/pps ns. Per-frame
        // nanosleep would cap the achievable rate near 20-30 kpps.
        long per_tick = pps >= 1000 ? pps / 1000 : 1;
        long long tick_ns = pps >= 1000 ? 1000000LL : 1000000000LL / pps;
        long long end = now_ns() + (long long)(secs * 1e9);
        long long next = now_ns();
        long sent = 0;
        while (now_ns() < end) {
            for (long i = 0; i < per_tick; i++) {
                ssize_t n = sendto(fd, frame, (size_t)size, 0,
                                   (struct sockaddr *)&dst, sizeof dst);
                if (n > 0) sent++;
            }
            next += tick_ns;
            long long delta = next - now_ns();
            if (delta > 0) sleep_ns(delta);
            else next = now_ns();
        }
        printf("sent %ld\n", sent);
        return 0;
    }

    if (strcmp(mode, "recv") == 0) {
        double secs = atof(argv[3]);
        struct timeval tv = { .tv_sec = 0, .tv_usec = 200000 };
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        unsigned char data[2048];
        long long end = now_ns() + (long long)(secs * 1e9);
        long count = 0;
        while (now_ns() < end) {
            ssize_t n = recv(fd, data, sizeof data, 0);
            if (n >= 0) count++;
        }
        printf("recv %ld\n", count);
        return 0;
    }

    if (strcmp(mode, "recvmac") == 0) {
        double secs = atof(argv[3]);
        struct timeval tv = { .tv_sec = 0, .tv_usec = 200000 };
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        unsigned char data[2048];
        struct { unsigned char mac[6]; long count; } table[32];
        int used = 0;
        long total = 0;
        long long end = now_ns() + (long long)(secs * 1e9);
        while (now_ns() < end) {
            ssize_t n = recv(fd, data, sizeof data, 0);
            if (n < 14) continue;
            if (data[12] != 0x21 || data[13] != 0x21) continue;
            total++;
            int slot = -1;
            for (int i = 0; i < used; i++)
                if (memcmp(table[i].mac, data + 6, 6) == 0) { slot = i; break; }
            if (slot < 0) {
                if (used >= 32) continue;
                slot = used++;
                memcpy(table[slot].mac, data + 6, 6);
                table[slot].count = 0;
            }
            table[slot].count++;
        }
        for (int i = 0; i < used; i++)
            printf("mac %02x:%02x:%02x:%02x:%02x:%02x %ld\n",
                   table[i].mac[0], table[i].mac[1], table[i].mac[2],
                   table[i].mac[3], table[i].mac[4], table[i].mac[5],
                   table[i].count);
        printf("total %ld\n", total);
        return 0;
    }

    fprintf(stderr, "unknown mode %s\n", mode);
    return 2;
}
