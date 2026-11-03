// Minimal AF_PACKET sender/receiver for the frame-gate throughput lab.
//
//   bench send <ifname> <pps> <seconds> <size>
//   bench recv <ifname> <seconds>
//
// Frames carry EtherType 0x2121 so they hit the same nft netdev rule as FIPS.
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

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: bench send|recv <if> <pps|secs> [secs] [size]\n");
        return 2;
    }
    const char *mode = argv[1];
    const char *ifname = argv[2];
    unsigned ifindex = if_nametoindex(ifname);
    if (!ifindex) { perror("if_nametoindex"); return 1; }

    int fd = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_ALL));
    if (fd < 0) { perror("socket"); return 1; }
    int buf = 8 * 1024 * 1024;
    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &buf, sizeof buf);
    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &buf, sizeof buf);

    struct sockaddr_ll sll;
    memset(&sll, 0, sizeof sll);
    sll.sll_family = AF_PACKET;
    sll.sll_protocol = htons(ETH_P_ALL);
    sll.sll_ifindex = (int)ifindex;
    if (bind(fd, (struct sockaddr *)&sll, sizeof sll) < 0) {
        perror("bind"); return 1;
    }

    if (strcmp(mode, "send") == 0) {
        if (argc < 5) { fprintf(stderr, "send needs pps and seconds\n"); return 2; }
        long pps = atol(argv[3]);
        double secs = atof(argv[4]);
        int size = argc > 5 ? atoi(argv[5]) : 64;
        if (size < 14 || size > 1500) size = 64;

        unsigned char frame[1600];
        memset(frame, 0xab, sizeof frame);
        memset(frame, 0xff, 6);            // broadcast
        frame[6] = 0x02; frame[7] = 0; frame[8] = 0;
        frame[9] = 0; frame[10] = 0; frame[11] = 1;
        frame[12] = 0x21; frame[13] = 0x21; // 0x2121

        struct sockaddr_ll dst;
        memset(&dst, 0, sizeof dst);
        dst.sll_family = AF_PACKET;
        dst.sll_protocol = htons(ETH_P_ALL);
        dst.sll_ifindex = (int)ifindex;
        dst.sll_halen = 6;
        memcpy(dst.sll_addr, frame, 6);

        // Pace in 1 ms bursts. Per-frame nanosleep has ~50-100 us granularity
        // and caps the achievable rate near 20-30 kpps; a burst per tick is
        // accurate up to several hundred kpps.
        long per_tick = pps > 0 ? pps / 1000 : 1;
        if (per_tick < 1) per_tick = 1;
        const long long tick_ns = 1000000LL;
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

    fprintf(stderr, "unknown mode %s\n", mode);
    return 2;
}
