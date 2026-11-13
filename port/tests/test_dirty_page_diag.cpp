#include "tlg_dirty_page_diag.h"
#include <cassert>
int main() {
    using TlgStats::DirtyPageBucket;
    assert(TlgStats::ClassifyDirtyPage(0) == DirtyPageBucket::Empty);
    assert(TlgStats::ClassifyDirtyPage(1) == DirtyPageBucket::AtMost16);
    assert(TlgStats::ClassifyDirtyPage(16) == DirtyPageBucket::AtMost16);
    assert(TlgStats::ClassifyDirtyPage(17) == DirtyPageBucket::Partial);
    assert(TlgStats::ClassifyDirtyPage(4095) == DirtyPageBucket::Partial);
    assert(TlgStats::ClassifyDirtyPage(4096) == DirtyPageBucket::Full);
    assert(TlgStats::RangeInsideBlock(0x1020, 0x10a0, 0x1000, 0x10a0));
    assert(!TlgStats::RangeInsideBlock(0x0fff, 0x1020, 0x1000, 0x10a0));
    assert(!TlgStats::RangeInsideBlock(0x1020, 0x10a1, 0x1000, 0x10a0));
}
