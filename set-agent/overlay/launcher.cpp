// Suspend-launch a target and inject a DLL before it runs any code.
//   launcher.exe "<target.exe>" "<overlay.dll>"
// CreateProcess(CREATE_SUSPENDED) -> CreateRemoteThread(LoadLibraryW) -> ResumeThread.
// The DLL then hooks the DXGI factory before the target creates its swapchain.
#include <windows.h>
#include <cstdio>

int wmain(int argc, wchar_t** argv) {
    if (argc < 3) { wprintf(L"usage: launcher <target.exe> <dll>\n"); return 1; }
    wchar_t dll[MAX_PATH]; GetFullPathNameW(argv[2], MAX_PATH, dll, nullptr);

    STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi = {};
    // Use a mutable command line buffer.
    wchar_t cmd[1024]; swprintf(cmd, 1024, L"\"%s\"", argv[1]);
    if (!CreateProcessW(argv[1], cmd, nullptr, nullptr, FALSE, CREATE_SUSPENDED,
                        nullptr, nullptr, &si, &pi)) {
        wprintf(L"CreateProcess failed %lu\n", GetLastError()); return 2;
    }
    wprintf(L"launched suspended pid=%lu\n", pi.dwProcessId);

    SIZE_T n = (wcslen(dll) + 1) * sizeof(wchar_t);
    void* mem = VirtualAllocEx(pi.hProcess, nullptr, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    WriteProcessMemory(pi.hProcess, mem, dll, n, nullptr);
    auto ll = (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleA("kernel32"), "LoadLibraryW");
    HANDLE t = CreateRemoteThread(pi.hProcess, nullptr, 0, ll, mem, 0, nullptr);
    if (!t) { wprintf(L"inject failed %lu\n", GetLastError()); TerminateProcess(pi.hProcess, 1); return 3; }
    WaitForSingleObject(t, 8000);
    DWORD code = 0; GetExitCodeThread(t, &code);
    wprintf(L"injected (LoadLibrary=0x%lx); resuming\n", code);

    ResumeThread(pi.hThread);
    CloseHandle(t); CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return code ? 0 : 4;
}
