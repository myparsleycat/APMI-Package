// Skins two meshes whose output buffers share a description, draws them with
// different index buffers and presents. Each frame writes the first output
// uint of mesh A and mesh B, read back before the draws.
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using Microsoft::WRL::ComPtr;

static void check(HRESULT hr, const char* action) {
    if (FAILED(hr)) throw std::runtime_error(std::string(action) + " failed: " + std::to_string(static_cast<unsigned>(hr)));
}

static ComPtr<ID3DBlob> compile(const char* source, const char* profile) {
    ComPtr<ID3DBlob> code, errors;
    const HRESULT hr = D3DCompile(source, std::strlen(source), nullptr, nullptr, nullptr, "main", profile,
                                  D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &code, &errors);
    if (errors) std::cerr.write(static_cast<char*>(errors->GetBufferPointer()), errors->GetBufferSize());
    check(hr, profile);
    return code;
}

struct Mesh {
    ComPtr<ID3D11ShaderResourceView> rest;
    ComPtr<ID3D11Buffer> output;
    ComPtr<ID3D11UnorderedAccessView> uav;
    ComPtr<ID3D11Buffer> ib;
};

static Mesh create_mesh(ID3D11Device* device, unsigned char rest_marker, const std::array<UINT, 3>& indices) {
    Mesh mesh;
    std::array<unsigned char, 40> rest{};
    rest[0] = rest_marker;
    D3D11_BUFFER_DESC desc{};
    desc.ByteWidth = static_cast<UINT>(rest.size());
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS;
    D3D11_SUBRESOURCE_DATA initial{rest.data(), 0, 0};
    ComPtr<ID3D11Buffer> rest_buffer;
    check(device->CreateBuffer(&desc, &initial, &rest_buffer), "Create rest buffer");
    D3D11_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = DXGI_FORMAT_R32_TYPELESS;
    srv.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
    srv.BufferEx.NumElements = desc.ByteWidth / 4;
    srv.BufferEx.Flags = D3D11_BUFFEREX_SRV_FLAG_RAW;
    check(device->CreateShaderResourceView(rest_buffer.Get(), &srv, &mesh.rest), "Create rest view");

    desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_VERTEX_BUFFER;
    check(device->CreateBuffer(&desc, nullptr, &mesh.output), "Create output buffer");
    D3D11_UNORDERED_ACCESS_VIEW_DESC uav{};
    uav.Format = DXGI_FORMAT_R32_TYPELESS;
    uav.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
    uav.Buffer.NumElements = desc.ByteWidth / 4;
    uav.Buffer.Flags = D3D11_BUFFER_UAV_FLAG_RAW;
    check(device->CreateUnorderedAccessView(mesh.output.Get(), &uav, &mesh.uav), "Create output view");

    D3D11_BUFFER_DESC index_desc{};
    index_desc.ByteWidth = static_cast<UINT>(sizeof(indices));
    index_desc.BindFlags = D3D11_BIND_INDEX_BUFFER;
    D3D11_SUBRESOURCE_DATA index_data{indices.data(), 0, 0};
    check(device->CreateBuffer(&index_desc, &index_data, &mesh.ib), "Create index buffer");
    return mesh;
}

int wmain(int argc, wchar_t** argv) {
    try {
        if (argc != 3) throw std::runtime_error("legacy_draw frames output");
        const int frames = std::stoi(argv[1]);
        HMODULE wrapper = LoadLibraryW(L".\\d3d11.dll");
        if (!wrapper) throw std::runtime_error("Cannot load d3d11.dll");
        auto create = reinterpret_cast<decltype(&D3D11CreateDeviceAndSwapChain)>(
            GetProcAddress(wrapper, "D3D11CreateDeviceAndSwapChain"));
        if (!create) throw std::runtime_error("Missing D3D11CreateDeviceAndSwapChain");

        WNDCLASSW window_class{};
        window_class.lpfnWndProc = DefWindowProcW;
        window_class.hInstance = GetModuleHandleW(nullptr);
        window_class.lpszClassName = L"APMILegacyDraw";
        RegisterClassW(&window_class);
        HWND window = CreateWindowW(window_class.lpszClassName, L"", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64,
                                    nullptr, nullptr, window_class.hInstance, nullptr);
        if (!window) throw std::runtime_error("Cannot create window");

        DXGI_SWAP_CHAIN_DESC swap{};
        swap.BufferDesc.Width = swap.BufferDesc.Height = 4;
        swap.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        swap.SampleDesc.Count = 1;
        swap.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        swap.BufferCount = 1;
        swap.OutputWindow = window;
        swap.Windowed = TRUE;
        D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0;
        ComPtr<IDXGISwapChain> chain;
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> context;
        check(create(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, &level, 1, D3D11_SDK_VERSION, &swap, &chain,
                     &device, nullptr, &context), "D3D11CreateDeviceAndSwapChain");

        auto cs_code = compile(R"(
            ByteAddressBuffer Rest : register(t0);
            RWByteAddressBuffer Output : register(u0);
            [numthreads(1, 1, 1)]
            void main() { Output.Store(0, 0x11); })", "cs_5_0");
        auto vs_code = compile(R"(
            float4 main(uint id : SV_VertexID) : SV_Position { return float4(0, 0, 0, 1); })", "vs_5_0");
        auto ps_code = compile(R"(
            float4 main() : SV_Target { return 0; })", "ps_5_0");
        ComPtr<ID3D11ComputeShader> cs;
        ComPtr<ID3D11VertexShader> vs;
        ComPtr<ID3D11PixelShader> ps;
        check(device->CreateComputeShader(cs_code->GetBufferPointer(), cs_code->GetBufferSize(), nullptr, &cs), "CreateComputeShader");
        check(device->CreateVertexShader(vs_code->GetBufferPointer(), vs_code->GetBufferSize(), nullptr, &vs), "CreateVertexShader");
        check(device->CreatePixelShader(ps_code->GetBufferPointer(), ps_code->GetBufferSize(), nullptr, &ps), "CreatePixelShader");

        std::array<Mesh, 2> meshes{create_mesh(device.Get(), 0, {0, 1, 2}), create_mesh(device.Get(), 1, {0, 2, 1})};

        ComPtr<ID3D11Texture2D> back_buffer;
        check(chain->GetBuffer(0, IID_PPV_ARGS(&back_buffer)), "GetBuffer");
        ComPtr<ID3D11RenderTargetView> rtv;
        check(device->CreateRenderTargetView(back_buffer.Get(), nullptr, &rtv), "CreateRenderTargetView");
        D3D11_BUFFER_DESC staging_desc{};
        staging_desc.ByteWidth = 40;
        staging_desc.Usage = D3D11_USAGE_STAGING;
        staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Buffer> staging;
        check(device->CreateBuffer(&staging_desc, nullptr, &staging), "Create staging buffer");

        D3D11_VIEWPORT viewport{0, 0, 4, 4, 0, 1};
        std::vector<UINT> results;
        for (int frame = 0; frame < frames; ++frame) {
            for (auto& mesh : meshes) {
                const UINT zero[4]{};
                context->ClearUnorderedAccessViewUint(mesh.uav.Get(), zero);
                ID3D11ShaderResourceView* rest = mesh.rest.Get();
                ID3D11UnorderedAccessView* uav = mesh.uav.Get();
                context->CSSetShader(cs.Get(), nullptr, 0);
                context->CSSetShaderResources(0, 1, &rest);
                context->CSSetUnorderedAccessViews(0, 1, &uav, nullptr);
                context->Dispatch(1, 1, 1);
                uav = nullptr;
                context->CSSetUnorderedAccessViews(0, 1, &uav, nullptr);
            }
            for (auto& mesh : meshes) {
                context->CopyResource(staging.Get(), mesh.output.Get());
                D3D11_MAPPED_SUBRESOURCE mapped{};
                check(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped), "Map");
                results.push_back(*static_cast<const UINT*>(mapped.pData));
                context->Unmap(staging.Get(), 0);
            }
            context->OMSetRenderTargets(1, rtv.GetAddressOf(), nullptr);
            context->RSSetViewports(1, &viewport);
            context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            context->VSSetShader(vs.Get(), nullptr, 0);
            context->PSSetShader(ps.Get(), nullptr, 0);
            for (auto& mesh : meshes) {
                const UINT stride = 40, offset = 0;
                ID3D11Buffer* vb = mesh.output.Get();
                context->IASetVertexBuffers(0, 1, &vb, &stride, &offset);
                context->IASetIndexBuffer(mesh.ib.Get(), DXGI_FORMAT_R32_UINT, 0);
                context->DrawIndexed(3, 0, 0);
            }
            ID3D11Buffer* none = nullptr;
            const UINT stride = 0, offset = 0;
            context->IASetVertexBuffers(0, 1, &none, &stride, &offset);
            check(chain->Present(0, 0), "Present");
        }
        std::ofstream file(std::filesystem::path(argv[2]), std::ios::binary);
        file.write(reinterpret_cast<const char*>(results.data()), static_cast<std::streamsize>(results.size() * sizeof(UINT)));
        if (!file) throw std::runtime_error("Cannot write output");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
