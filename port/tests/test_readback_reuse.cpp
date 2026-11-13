#include "tlg_readback_reuse.h"
#include <cassert>

int main() {
    TlgStats::ReadbackReuse<2> reuse;
    reuse.Note(0x1000, 100, false);
    reuse.Note(0x1fff, 110, false); // same page, <16 ms
    reuse.Note(0x1000, 140, true);  // same page, 16-99 ms
    reuse.Note(0x1000, 640, false); // 100-999 ms
    reuse.Note(0x1000, 1640, false); // >=1000 ms
    auto counts = reuse.Take();
    assert(counts.first == 1 && counts.fast == 1 && counts.medium == 1);
    assert(counts.slow == 1 && counts.old == 1 && counts.writes == 1);
    assert(reuse.Take().first == 0);
    reuse.Note(0x1000, 1650, false); // history survives a reporting interval
    assert(reuse.Take().fast == 1);
    reuse.Note(0x3000, 1700, false); // same slot as page 1
    counts = reuse.Take();
    assert(counts.first == 1 && counts.collisions == 1);
    reuse.Note(0x3fff, 1716, false, 2);
    counts = reuse.Take();
    assert(counts.medium == 1 && counts.crossing == 1);
    reuse.NoteOrigin({0x1000, 0x2000, 64, TLG_OP_COPY});
    reuse.NoteOrigin({0x1000, 0x1020, 64, TLG_OP_MOVE});
    reuse.NoteOrigin({0x1000, 0, 16, TLG_OP_FILL});
    reuse.NoteOrigin({});
    counts = reuse.Take();
    assert(counts.copy == 1 && counts.move == 1 && counts.fill == 1 && counts.other == 1);
    assert(counts.eligible64 == 1);
    TlgStats::FaultSiteCounts<2> sites;
    sites.Note(0x100);
    sites.Note(0x100);
    sites.Note(0x200);
    sites.Note(0x300);
    auto site_counts = sites.Take();
    assert(site_counts.sites[0].key == 0x100 && site_counts.sites[0].count == 2);
    assert(site_counts.sites[1].key == 0x200 && site_counts.overflow == 1);
    assert(sites.Take().sites[0].count == 0);
}
