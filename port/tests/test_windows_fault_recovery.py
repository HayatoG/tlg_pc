"""Exercise the production Windows exception handler with real protected-memory faults.

No renderer or game files are needed. The GPU callback fails immediately if a speculative
read reaches it, instead of letting the original readback/pipeline-cache deadlock hang CI.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "compat_win.h"

typedef tlg_jmp_buf sigjmp_buf;
static __thread sigjmp_buf *runtime_fault_recover;
typedef struct { int unused; } IsaRegs;
static void *isa_table;
static unsigned char *image;
static int gpu_enabled=1;
static volatile int speculative_expected, gpu_calls, nested_read, nested_recovered;
static volatile unsigned char *page, *other;
static void isa_context_regs(CONTEXT *c, IsaRegs *r, int to) { (void)c; (void)r; (void)to; }
static int isa_rewrite_trap(void *table, uintptr_t at, IsaRegs *regs, void *xmm, uintptr_t *rip) {
    (void)table; (void)at; (void)regs; (void)xmm; (void)rip; return 0;
}
static LONG fatal_exception(EXCEPTION_POINTERS *info) { (void)info; return EXCEPTION_CONTINUE_SEARCH; }
static int tlggpu_handle_fault(void *context, void *address) {
    (void)context;
    ++gpu_calls;
    if (speculative_expected) {
        fputs("FAIL: speculative worker entered GPU readback before recovery\n",stderr);
        ExitProcess(99);
    }
    if (address==(void *)other) {
        fputs("FAIL: guarded read inside the fault handler entered GPU readback\n",stderr);
        ExitProcess(96);
    }
    if (nested_read) {
        /* As the texture cache's first image hash in the write-fault handler: a guarded read
         * of another protected page faults again inside this handler and must recover. */
        sigjmp_buf recovery;
        if (!tlg_setjmp(recovery)) {
            runtime_fault_recover=&recovery;
            volatile unsigned char value=*other;
            (void)value;
            ExitProcess(95);
        }
        nested_recovered+=runtime_fault_recover==NULL;
    }
    DWORD old;
    if (!VirtualProtect((void *)page,4096,PAGE_READWRITE,&old)) ExitProcess(98);
    return 1;
}

/* The exact production handler is inserted here by the test. */
__HANDLER__

static void require(int condition, const char *message) {
    if (!condition) { fprintf(stderr,"FAIL: %s\n",message); ExitProcess(97); }
}
int main(void) {
    PVOID handler=AddVectoredExceptionHandler(1,vectored_fault);
    require(handler!=NULL,"install handler");
    page=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_NOACCESS);
    require(page!=NULL,"allocate protected page");

    /* Repeated recoveries exercise the context trampoline and TLS reset too. */
    for (int iteration=0; iteration<100; ++iteration) {
        sigjmp_buf recovery;
        speculative_expected=1;
        if (!tlg_setjmp(recovery)) {
            runtime_fault_recover=&recovery;
            volatile unsigned char value=*page;
            (void)value;
            require(0,"speculative read must recover");
        }
        require(runtime_fault_recover==NULL,"clear speculative TLS recovery point");
        require(gpu_calls==0,"speculative read must not enqueue GPU work");
    }
    speculative_expected=0;
    volatile unsigned char value=*page;
    require(value==0 && gpu_calls==1,"normal read still resolves through GPU tracking");

    /* A write-protection fault must still use the GPU tracking callback. */
    DWORD old;
    require(VirtualProtect((void *)page,4096,PAGE_READONLY,&old),"protect write");
    *page=42;
    require(*page==42 && gpu_calls==2,"normal write still resolves through GPU tracking");

    /* A guarded read inside the GPU fault handler recovers from its nested fault and the
     * outer write still completes (TLG freeze 2026-10-27: it waited for a second readback). */
    other=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_NOACCESS);
    require(other!=NULL,"allocate second protected page");
    require(VirtualProtect((void *)page,4096,PAGE_READONLY,&old),"protect write again");
    nested_read=1;
    *page=7;
    nested_read=0;
    require(*page==7 && gpu_calls==3 && nested_recovered==1,
            "guarded read in the fault handler recovers; the write completes");
    VirtualFree((void *)other,0,MEM_RELEASE);
    VirtualFree((void *)page,0,MEM_RELEASE);
    RemoveVectoredExceptionHandler(handler);
    puts("PASS: speculative recovery precedes readback; normal read/write tracking preserved; "
         "nested guarded read recovers");
    return 0;
}
'''


@unittest.skipUnless(os.name == 'nt', 'Windows exception handling only')
class WindowsFaultRecoveryTest(unittest.TestCase):
    def test_speculative_fault_recovers_before_gpu_readback(self):
        compiler = os.environ.get('TLG_TEST_CLANG') or shutil.which('clang')
        local = ROOT / 'out/native-tools/msys64/clang64/bin/clang.exe'
        if not compiler and local.is_file():
            compiler = str(local)
        if not compiler:
            self.skipTest('MSYS2 CLANG64 compiler unavailable; set TLG_TEST_CLANG')
        source = (ROOT / 'src/probe.c').read_text(encoding='utf-8')
        start = source.index('static LONG CALLBACK vectored_fault(')
        end = source.index('static LONG WINAPI unhandled_fault(', start)
        harness = HARNESS.replace('__HANDLER__', source[start:end])
        output = ROOT / 'out'
        output.mkdir(exist_ok=True)
        env = dict(os.environ)
        env['PATH'] = str(Path(compiler).resolve().parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory(dir=output) as folder:
            env['TEMP'] = env['TMP'] = folder
            test_source = Path(folder) / 'test.c'
            executable = Path(folder) / 'fault-recovery.exe'
            test_source.write_text(harness, encoding='utf-8')
            built = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                    '-I' + str(ROOT / 'src'), str(test_source), str(ROOT / 'src/compat_win.c'),
                                    '-lbcrypt', '-o', str(executable)], env=env, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(executable)], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('normal read/write tracking preserved', result.stdout)


if __name__ == '__main__':
    unittest.main()
