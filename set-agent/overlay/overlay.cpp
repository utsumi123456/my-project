// Set Agent overlay — TAD-4b: factory-hook approach.
//
// Instead of guessing the swapchain vtable from a dummy D3D11 device (which does
// NOT match rekordbox 7's real D3D12 swapchain class), we hook the DXGI factory's
// CreateSwapChainForHwnd / CreateSwapChain. When rekordbox creates its real
// swapchain we patch THAT instance's Present/Present1 vtable — so the hook fires
// regardless of whether the app renders with D3D11 or D3D12.
//
// This requires the DLL to be loaded BEFORE rekordbox creates its swapchain, i.e.
// injected into a CREATE_SUSPENDED process (see launcher.cpp).
//
// Drawing: if the swapchain's device is D3D11 we paint one rectangle (ClearView).
// If it's D3D12 we (for this spike) only prove the hook fires and log the geometry;
// the D3D12 draw path is the next step.

#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <d3d12.h>
#include <dxgi.h>
#include <dxgi1_2.h>
#include <cstdio>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

static const char* LOG = "C:\\Users\\7166700\\source\\setagent\\overlay.log";
static void logf(const char* fmt, ...) {
    char buf[512]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof(buf), fmt, ap); va_end(ap);
    FILE* f = nullptr; fopen_s(&f, LOG, "a"); if (f) { fprintf(f, "%s\n", buf); fclose(f); }
}

// ---- Present / Present1 hooks on the real swapchain instance ----------------
using PresentFn  = HRESULT(__stdcall*)(IDXGISwapChain*, UINT, UINT);
using Present1Fn = HRESULT(__stdcall*)(IDXGISwapChain1*, UINT, UINT, const DXGI_PRESENT_PARAMETERS*);
static PresentFn  oPresent  = nullptr;
static Present1Fn oPresent1 = nullptr;
static bool g_scHooked = false;

static ID3D11Device*         g_dev  = nullptr;
static ID3D11DeviceContext1* g_ctx1 = nullptr;
static ID3D11RenderTargetView* g_rtv = nullptr;
static bool g_isD3D12 = false;
static ULONGLONG g_frames = 0;

static void paint(IDXGISwapChain* sc) {
    g_frames++;
    if (g_isD3D12) {
        if (g_frames == 1 || g_frames == 120)
            logf("overlay: Present1 FIRING on real swapchain (D3D12) frame=%llu", g_frames);
        return;  // D3D12 draw path is the next step; hook firing is proven here.
    }
    if (!g_rtv) {
        if (FAILED(sc->GetDevice(__uuidof(ID3D11Device), (void**)&g_dev))) return;
        ID3D11DeviceContext* ctx = nullptr; g_dev->GetImmediateContext(&ctx);
        if (ctx) ctx->QueryInterface(__uuidof(ID3D11DeviceContext1), (void**)&g_ctx1);
        ID3D11Texture2D* back = nullptr;
        if (SUCCEEDED(sc->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&back)) && back) {
            g_dev->CreateRenderTargetView(back, nullptr, &g_rtv); back->Release();
            logf("overlay: RTV created (D3D11); drawing rectangle");
        }
    }
    if (g_rtv && g_ctx1) {
        DXGI_SWAP_CHAIN_DESC d; sc->GetDesc(&d);
        D3D11_RECT r; r.right = (LONG)d.BufferDesc.Width - 24; r.left = r.right - 320; r.top = 24; r.bottom = 144;
        if (r.left < 0) r.left = 0;
        float t = (float)((g_frames % 240) / 240.0);
        float col[4] = { 0.10f + 0.20f * t, 0.55f, 0.90f - 0.30f * t, 1.0f };
        g_ctx1->ClearView(g_rtv, col, &r, 1);
    }
}

static HRESULT __stdcall hkPresent(IDXGISwapChain* sc, UINT s, UINT f) { paint(sc); return oPresent(sc, s, f); }
static HRESULT __stdcall hkPresent1(IDXGISwapChain1* sc, UINT s, UINT f, const DXGI_PRESENT_PARAMETERS* p) {
    paint(sc); return oPresent1(sc, s, f, p);
}

static void patchEntry(void** vt, int i, void* hook, void** orig) {
    *orig = vt[i]; DWORD o;
    VirtualProtect(&vt[i], sizeof(void*), PAGE_EXECUTE_READWRITE, &o);
    vt[i] = hook; VirtualProtect(&vt[i], sizeof(void*), o, &o);
}

// Patch Present(8) + Present1(22) on the actual swapchain rekordbox just created.
static void hookRealSwapchain(IDXGISwapChain* sc) {
    if (g_scHooked || !sc) return;
    // classify the device so paint() picks the right path
    ID3D12Device* d12 = nullptr; ID3D11Device* d11 = nullptr;
    if (SUCCEEDED(sc->GetDevice(__uuidof(ID3D12Device), (void**)&d12)) && d12) { g_isD3D12 = true; d12->Release(); }
    else if (SUCCEEDED(sc->GetDevice(__uuidof(ID3D11Device), (void**)&d11)) && d11) { g_isD3D12 = false; d11->Release(); }
    void** vt = *reinterpret_cast<void***>(sc);
    patchEntry(vt, 8, (void*)&hkPresent, (void**)&oPresent);
    IDXGISwapChain1* sc1 = nullptr;
    if (SUCCEEDED(sc->QueryInterface(__uuidof(IDXGISwapChain1), (void**)&sc1)) && sc1) {
        void** vt1 = *reinterpret_cast<void***>(sc1);
        patchEntry(vt1, 22, (void*)&hkPresent1, (void**)&oPresent1); sc1->Release();
    }
    g_scHooked = true;
    logf("overlay: REAL swapchain hooked (%s), Present+Present1 patched", g_isD3D12 ? "D3D12" : "D3D11");
}

// ---- Factory hooks: catch the moment rekordbox creates its swapchain --------
using CSCFHFn = HRESULT(__stdcall*)(IDXGIFactory2*, IUnknown*, HWND, const DXGI_SWAP_CHAIN_DESC1*,
                                    const DXGI_SWAP_CHAIN_FULLSCREEN_DESC*, IDXGIOutput*, IDXGISwapChain1**);
using CSCFn   = HRESULT(__stdcall*)(IDXGIFactory*, IUnknown*, DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**);
static CSCFHFn oCSCFH = nullptr;
static CSCFn   oCSC   = nullptr;

static HRESULT __stdcall hkCSCFH(IDXGIFactory2* self, IUnknown* dev, HWND hwnd,
        const DXGI_SWAP_CHAIN_DESC1* d, const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fd,
        IDXGIOutput* out, IDXGISwapChain1** pp) {
    HRESULT hr = oCSCFH(self, dev, hwnd, d, fd, out, pp);
    logf("overlay: CreateSwapChainForHwnd hit (hwnd=%p, %ux%u) hr=0x%lx", hwnd, d ? d->Width : 0, d ? d->Height : 0, hr);
    if (SUCCEEDED(hr) && pp && *pp) hookRealSwapchain(*pp);
    return hr;
}
static HRESULT __stdcall hkCSC(IDXGIFactory* self, IUnknown* dev, DXGI_SWAP_CHAIN_DESC* d, IDXGISwapChain** pp) {
    HRESULT hr = oCSC(self, dev, d, pp);
    logf("overlay: CreateSwapChain hit hr=0x%lx", hr);
    if (SUCCEEDED(hr) && pp && *pp) hookRealSwapchain(*pp);
    return hr;
}

typedef HRESULT(WINAPI* CreateFactory2Fn)(UINT, REFIID, void**);

static bool installFactoryHooks() {
    // Get a factory to read the shared IDXGIFactory vtable (dxgi.dll implementation).
    HMODULE dxgi = LoadLibraryA("dxgi.dll");
    if (!dxgi) return false;
    auto CreateDXGIFactory2 = (CreateFactory2Fn)GetProcAddress(dxgi, "CreateDXGIFactory2");
    IDXGIFactory2* f = nullptr;
    HRESULT hr = E_FAIL;
    if (CreateDXGIFactory2) hr = CreateDXGIFactory2(0, __uuidof(IDXGIFactory2), (void**)&f);
    if (FAILED(hr) || !f) return false;
    void** vt = *reinterpret_cast<void***>(f);
    patchEntry(vt, 10, (void*)&hkCSC,   (void**)&oCSC);    // IDXGIFactory::CreateSwapChain
    patchEntry(vt, 15, (void*)&hkCSCFH, (void**)&oCSCFH);  // IDXGIFactory2::CreateSwapChainForHwnd
    f->Release();
    logf("overlay: factory hooks installed (CreateSwapChain[10]+CreateSwapChainForHwnd[15])");
    return true;
}

static DWORD WINAPI worker(LPVOID) {
    logf("overlay: injected (factory-hook build)");
    for (int i = 0; i < 40 && !installFactoryHooks(); ++i) Sleep(100);
    return 0;
}

BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) { DisableThreadLibraryCalls(h); CreateThread(nullptr, 0, worker, nullptr, 0, nullptr); }
    return TRUE;
}
