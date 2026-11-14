#include "tlg_readback_window.h"
#include <cassert>
int main() {
    assert(TlgReadback::WindowBytes(nullptr) == 512 * 1024);
    assert(TlgReadback::WindowBytes("") == 512 * 1024);
    assert(TlgReadback::WindowBytes("2048") == 2048 * 1024);
    assert(TlgReadback::WindowBytes("4096") == 4096 * 1024);
    assert(TlgReadback::WindowBytes("128") == 128 * 1024);
    assert(TlgReadback::WindowBytes("300") == 512 * 1024);
    assert(TlgReadback::WindowBytes("8192") == 512 * 1024);
    assert(TlgReadback::WindowBytes("-1") == 512 * 1024);
    assert(TlgReadback::WindowBytes("2048junk") == 512 * 1024);
}
