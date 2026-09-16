// Minimal DLL injector: inject.exe <pid|process.exe> <path-to-dll>
// Uses CreateRemoteThread(LoadLibraryW). Spike-grade; for the PoC only.
#include <windows.h>
#include <tlhelp32.h>
#include <cstdio>
#include <cwchar>

static DWORD pidByName(const wchar_t* name) {
    DWORD pid = 0; HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe = { sizeof(pe) };
    if (Process32FirstW(snap, &pe)) do {
        if (_wcsicmp(pe.szExeFile, name) == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32NextW(snap, &pe));
    CloseHandle(snap); return pid;
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 3) { wprintf(L"usage: inject <pid|name.exe> <dll>\n"); return 1; }
    DWORD pid = _wtoi(argv[1]);
    if (!pid) pid = pidByName(argv[1]);
    if (!pid) { wprintf(L"process not found\n"); return 2; }

    wchar_t full[MAX_PATH]; GetFullPathNameW(argv[2], MAX_PATH, full, nullptr);
    HANDLE p = OpenProcess(PROCESS_ALL_ACCESS, FALSE, pid);
    if (!p) { wprintf(L"OpenProcess failed %lu\n", GetLastError()); return 3; }

    SIZE_T n = (wcslen(full) + 1) * sizeof(wchar_t);
    void* mem = VirtualAllocEx(p, nullptr, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    WriteProcessMemory(p, mem, full, n, nullptr);
    auto ll = (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleA("kernel32"), "LoadLibraryW");
    HANDLE t = CreateRemoteThread(p, nullptr, 0, ll, mem, 0, nullptr);
    if (!t) { wprintf(L"CreateRemoteThread failed %lu\n", GetLastError()); return 4; }
    WaitForSingleObject(t, 5000);
    DWORD code = 0; GetExitCodeThread(t, &code);
    wprintf(L"injected into pid %lu (LoadLibrary ret 0x%lx)\n", pid, code);
    CloseHandle(t); CloseHandle(p); return code ? 0 : 5;
}
